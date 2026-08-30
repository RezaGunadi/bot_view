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

# Diklik dua kali dari file manager? Di Lubuntu, tombol "Execute" menjalankan
# skrip TANPA terminal: semua output hilang dan layar seolah tidak bereaksi.
# Kalau begitu, buka terminal sendiri supaya progres dan error kelihatan.
if [ ! -t 1 ] && [ -z "${PLAYLIST_STUDIO_NO_TERMINAL:-}" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    self="$(pwd)/$(basename "$0")"
    inner="$(printf '%q ' "$self" "$@")"
    # Jaga terminal tetap terbuka setelah selesai, supaya pesan error terbaca.
    post='; rc=$?; echo; read -r -p "Selesai. Tekan Enter untuk menutup..." _; exit $rc'
    for term in x-terminal-emulator qterminal lxterminal xfce4-terminal mate-terminal konsole gnome-terminal xterm; do
        if command -v "$term" >/dev/null 2>&1; then
            export PLAYLIST_STUDIO_NO_TERMINAL=1
            exec "$term" -e bash -c "$inner$post"
        fi
    done
    # Tidak ada emulator terminal yang dikenali - lanjut saja tanpa terminal.
fi

echo "[start] Playlist Studio - $(pwd)"

# Sehat = ada DAN pip-nya jalan. Venv yang dibuat waktu python3-venv belum
# lengkap punya bin/python tapi tanpa pip, dan itu bukan venv yang bisa dipakai.
venv_ready() {
    [ -x .venv/bin/python ] && .venv/bin/python -m pip --version >/dev/null 2>&1
}

# Belum pernah disetup -> pasang dulu. setup-linux.sh berhenti sendiri dengan
# pesan yang jelas kalau ada yang gagal, dan `set -e` di sini ikut berhenti.
if ! venv_ready && [ -f setup-linux.sh ]; then
    echo "[start] .venv belum siap - menjalankan setup-linux.sh dulu (sekali saja)."
    bash setup-linux.sh
fi

if [ -x .venv/bin/python ]; then
    # Lewat .venv langsung, tidak bergantung pada bootstrap di dalam run.py.
    exec .venv/bin/python run.py "$@"
fi

echo "[start] .venv tidak ada dan setup-linux.sh juga tidak ada." >&2
echo "[start] Mencoba lewat python3 sistem - kemungkinan besar gagal." >&2
exec python3 run.py "$@"
