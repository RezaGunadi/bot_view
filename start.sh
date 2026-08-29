#!/usr/bin/env bash
#
# Jalankan Playlist Studio. Semua argumen diteruskan ke run.py, contoh:
#
#     ./start.sh --port 8123
#     ./start.sh --install-autostart
#
# Kalau .venv belum ada, jalankan dulu:  bash setup-linux.sh
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python run.py "$@"
fi

echo "[start] .venv belum ada - jalankan dulu:  bash setup-linux.sh" >&2
echo "[start] Mencoba lewat python3 sistem..." >&2
exec python3 run.py "$@"
