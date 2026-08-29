#!/usr/bin/env bash
#
# Jalankan Playlist Studio. Semua argumen diteruskan ke run.py, contoh:
#
#     ./start.sh --port 8123
#     ./start.sh --install-autostart
#
# Run pertama otomatis memanggil setup-linux.sh (pasang Python, browser,
# wmctrl, dependency). Run berikutnya langsung jalan.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -euo pipefail
cd "$(dirname "$0")"

# Belum pernah disetup -> pasang dulu. setup-linux.sh berhenti sendiri dengan
# pesan yang jelas kalau ada yang gagal, dan `set -e` di sini ikut berhenti.
if [ ! -x .venv/bin/python ] && [ -f setup-linux.sh ]; then
    echo "[start] .venv belum ada - menjalankan setup-linux.sh dulu (sekali saja)."
    bash setup-linux.sh
fi

if [ -x .venv/bin/python ]; then
    # Lewat .venv langsung, tidak bergantung pada bootstrap di dalam run.py.
    exec .venv/bin/python run.py "$@"
fi

echo "[start] .venv tidak ada dan setup-linux.sh juga tidak ada." >&2
echo "[start] Mencoba lewat python3 sistem - kemungkinan besar gagal." >&2
exec python3 run.py "$@"
