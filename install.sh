#!/data/data/com.termux/files/usr/bin/bash
# language: bash, file: install.sh
# One-shot installer — Termux or Linux.
set -e

if [ -d /data/data/com.termux/files/usr ]; then
    echo "[*] Termux detected"
    pkg update -y && pkg upgrade -y
    pkg install -y python termux-api git
    termux-setup-storage || true
    pip install requests
else
    echo "[*] Linux detected"
    if command -v apt >/dev/null; then
        sudo apt update && sudo apt install -y python3 python3-pip
    elif command -v pacman >/dev/null; then
        sudo pacman -Sy --noconfirm python python-pip
    fi
    pip3 install --user requests
fi

echo "[*] Done. Run:"
echo "    C2_URL=http://YOUR-SERVER:8080 python client/client.py"
