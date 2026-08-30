#!/usr/bin/env bash
#
# Playlist Studio - pemasangan sekali jalan untuk Lubuntu / Ubuntu / Debian.
#
#     bash setup-linux.sh
#
# Yang dikerjakan: Python 3.10+, modul venv, browser, wmctrl, xrandr, lalu
# dependency Python dipasang ke .venv di dalam folder ini. Tidak ada paket
# Python yang ditulis ke Python sistem.
#
# Sesudah ini, jalankan sehari-hari dengan:  ./start.sh   (atau python3 run.py)

# Kalau dipanggil pakai `sh`, ulangi dengan bash - skrip ini pakai bash.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mGAGAL:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

printf '==============================================================\n'
printf '  Playlist Studio - pemasangan untuk Lubuntu / Ubuntu / Debian\n'
printf '==============================================================\n'

# --- 0. Prasyarat skrip ini sendiri ------------------------------------------
have apt-get || die "Skrip ini untuk Debian/Ubuntu/Lubuntu (butuh apt-get).
       Di distro lain, pasang manual: python3 (3.10+), python3-venv,
       chromium/firefox, wmctrl, xrandr. Lalu jalankan: python3 run.py"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    have sudo || die "Butuh sudo untuk memasang paket sistem."
    SUDO="sudo"
    info "Beberapa langkah butuh sudo - password mungkin diminta."
fi

APT_UPDATED=0
apt_install() {
    if [ "$APT_UPDATED" -eq 0 ]; then
        say "Memperbarui daftar paket"
        $SUDO apt-get update -qq || true
        APT_UPDATED=1
    fi
    $SUDO apt-get install -y "$@"
}

# --- 1. Python 3.10+ ----------------------------------------------------------
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

pick_python() {
    local c
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
        if have "$c" && py_ok "$c"; then
            PY="$(command -v "$c")"
            return 0
        fi
    done
    return 1
}

say "Mencari Python 3.10 atau lebih baru"
PY=""
if ! pick_python; then
    info "Belum ada - memasang lewat apt."
    apt_install python3 >/dev/null 2>&1 || true
    if ! pick_python; then
        for pkg in python3.12 python3.11 python3.10; do
            apt_install "$pkg" >/dev/null 2>&1 || continue
            if pick_python; then break; fi
        done
    fi
fi
[ -n "$PY" ] || die "Tidak menemukan Python 3.10+ dan apt tidak menyediakannya.
       Distro ini kemungkinan terlalu lama. Upgrade ke Ubuntu 22.04+,
       atau pasang Python baru lewat PPA deadsnakes."
info "Pakai: $PY ($("$PY" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'))"

# --- 2. Modul venv ------------------------------------------------------------
# python3 bawaan Debian/Ubuntu datang tanpa pip dan tanpa ensurepip; keduanya
# ada di paket terpisah. Sejak PEP 668 Python sistem juga menolak ditulisi pip,
# jadi .venv memang satu-satunya jalur yang benar di sini.
PYTAG="$("$PY" -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"
if ! "$PY" -c 'import venv, ensurepip' >/dev/null 2>&1; then
    say "Memasang modul venv ($PYTAG-venv)"
    apt_install "${PYTAG}-venv" || apt_install python3-venv \
        || die "Tidak bisa memasang modul venv. Coba manual:
       sudo apt install ${PYTAG}-venv"
fi

# --- 3. Browser untuk window stream -------------------------------------------
say "Memeriksa browser untuk window stream"
BROWSER=""
for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge firefox; do
    if have "$b"; then BROWSER="$b"; break; fi
done
if [ -z "$BROWSER" ]; then
    info "Belum ada - memasang."
    for pkg in chromium chromium-browser firefox; do
        if apt_install "$pkg" >/dev/null 2>&1; then BROWSER="$pkg"; break; fi
    done
fi
if [ -n "$BROWSER" ]; then
    info "Pakai: $BROWSER"
    if [ "$BROWSER" = "firefox" ]; then
        info "Firefox didukung penuh - profil tiap stream diisolasi lewat -profile,"
        info "dan window-nya ditempatkan lewat wmctrl."
        info "Chromium menempatkan window sedikit lebih rapi karena punya flag posisi"
        info "sendiri. Kalau mau:  sudo apt install chromium"
    fi
else
    info "PERINGATAN: tidak ada browser yang terpasang. Window stream tidak akan"
    info "            terbuka. Pasang manual: sudo apt install chromium"
fi

# --- 4. Penempatan window (wmctrl) + deteksi monitor (xrandr) ------------------
say "Memeriksa wmctrl & xrandr"
if have wmctrl; then
    info "wmctrl sudah ada."
else
    info "Memasang wmctrl (penempatan window per monitor)."
    apt_install wmctrl >/dev/null 2>&1         || info "PERINGATAN: wmctrl gagal dipasang - stream bisa menumpuk di satu monitor."
fi
if have xrandr; then
    info "xrandr sudah ada."
else
    info "Memasang xrandr (deteksi daftar monitor)."
    apt_install x11-xserver-utils >/dev/null 2>&1         || info "PERINGATAN: xrandr gagal dipasang - monitor tidak bisa dideteksi."
fi

# --- 5. Dependency Python di dalam .venv --------------------------------------
say "Menyiapkan .venv"
# Ada bin/python saja belum tentu sehat: kalau venv sempat dibuat waktu paket
# python3-venv belum lengkap, foldernya jadi tapi pip-nya tidak pernah ikut.
if [ -x .venv/bin/python ] && ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    info ".venv lama tidak punya pip - dibuang dan dibuat ulang."
    rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv || die "Gagal membuat .venv. Coba: sudo apt install ${PYTAG}-venv"
    info "Dibuat: $(pwd)/.venv"
else
    info "Sudah ada dan sehat - dipakai lagi."
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    die ".venv terbentuk tapi tanpa pip. Pasang paketnya lalu ulangi:
       sudo apt install ${PYTAG}-venv"
fi

say "Memasang dependency Python"
.venv/bin/python -m pip install --upgrade pip --disable-pip-version-check -q || true
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt \
    || die "Gagal memasang dependency. Pastikan ada koneksi internet lalu ulangi."

# --- 6. Database --------------------------------------------------------------
say "Menyiapkan database"
.venv/bin/python run.py --migrate-only

# --- 7. Selesai ---------------------------------------------------------------
printf '\n==============================================================\n'
printf '  SELESAI\n'
printf '==============================================================\n\n'
printf '  Jalankan aplikasinya:\n\n'
printf '      ./start.sh\n\n'
printf '  Bisa juga:  python3 run.py   (otomatis lewat .venv yang barusan dibuat)\n'
printf '  GUI-nya di: http://localhost:8000\n\n'
printf '  Supaya nyala sendiri tiap komputer dihidupkan:\n'
printf '      ./start.sh --install-autostart\n\n'

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    printf '\033[1;33m  PERHATIAN: sesi ini Wayland.\033[0m Deteksi monitor dan penempatan window\n'
    printf '  butuh X11. Logout, lalu di layar login pilih sesi X11/Xorg -\n'
    printf '  kalau tidak, semua stream akan menumpuk di satu monitor.\n\n'
fi
