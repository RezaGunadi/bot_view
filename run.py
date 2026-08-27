"""Runner: satu perintah untuk semuanya.

    python run.py

Yang dikerjakan berurutan (masing-masing SKIP kalau sudah beres):
    1. Cek dependency  -> install yang kurang saja, lewati yang sudah ada.
    2. Migrasi database -> bikin SQLite kalau belum ada, skip kalau sudah terkini.
    3. Jalankan server + buka GUI.

Opsi:
    --no-browser    jangan buka GUI otomatis
    --port 8123     ganti port
    --migrate-only  cuma siapkan dependency + database lalu keluar
    --reset-db      backup db lama, bikin ulang dari nol
    --skip-deps     lewati pengecekan dependency
    --reload        auto-reload untuk development

Server sengaja hanya bind ke 127.0.0.1 — tidak bisa diakses dari jaringan lain.
"""
import argparse
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
# Saat jadi .exe: data ditulis di sebelah exe. Saat dari source: di folder proyek.
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
if not FROZEN:
    sys.path.insert(0, str(BASE_DIR))

if not FROZEN and sys.version_info < (3, 10):
    print("Butuh Python 3.10 atau lebih baru (terpasang: "
          f"{sys.version_info.major}.{sys.version_info.minor}).")
    print("Download di https://www.python.org/downloads/ lalu jalankan lagi.")
    sys.exit(1)

# Modul yang harus bisa di-import -> paket pip yang menyediakannya.
# Sengaja pakai batas bawah, bukan versi terkunci: Python yang baru rilis butuh
# rilis terbaru paketnya. Juga tanpa uvicorn[standard] — extra itu menarik paket
# terkompilasi (httptools/uvloop/watchfiles) yang wheel-nya sering telat untuk
# Python versi baru, padahal untuk server lokal tidak dibutuhkan.
REQUIRED = {
    "fastapi": "fastapi>=0.115",
    "uvicorn": "uvicorn>=0.34",
    "dotenv": "python-dotenv>=1.0",
    "multipart": "python-multipart>=0.0.9",   # upload file di FastAPI
    "openpyxl": "openpyxl>=3.1",              # baca/tulis .xlsx
}


def ensure_deps() -> bool:
    """Install dependency yang belum ada. Yang sudah terpasang dilewati."""
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        print(f"[deps] {len(REQUIRED)} dependency sudah terpasang — skip.")
        return True

    print(f"[deps] Kurang {len(missing)}: {', '.join(missing)}")
    print("[deps] Memasang sekarang (sekali saja, run berikutnya langsung skip)...")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing]
    if subprocess.call(cmd) != 0:
        print("\n[deps] GAGAL memasang dependency.")
        print("       Coba manual:  " + " ".join(cmd))
        return False

    importlib.invalidate_caches()
    still = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if still:
        print(f"[deps] Masih belum terbaca: {', '.join(still)}. Coba jalankan ulang run.py.")
        return False
    print("[deps] Selesai.")
    return True


def _startup_shortcut() -> Path:
    return (Path(os.environ.get("APPDATA", Path.home()))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            / "PlaylistStudio.cmd")


def install_autostart(remove: bool = False):
    """Jalankan otomatis saat login — mini PC tinggal dinyalakan."""
    if FROZEN:
        command = f'"{Path(sys.executable).resolve()}"'
    else:
        command = f'"{sys.executable}" "{Path(__file__).resolve()}"'

    if sys.platform == "win32":
        _autostart_windows(command, remove)
    elif sys.platform.startswith("linux"):
        _autostart_linux(command, remove)
    else:
        print("[autostart] Belum didukung di platform ini.")


def _autostart_windows(command: str, remove: bool):
    target = _startup_shortcut()
    if remove:
        if target.exists():
            target.unlink()
            print(f"[autostart] Dihapus: {target}")
        else:
            print("[autostart] Tidak ada yang perlu dihapus.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '\r\n'.join([
            "@echo off",
            "REM Dibuat oleh Playlist Studio (run.py --install-autostart)",
            f'cd /d "{BASE_DIR}"',
            f'start "" {command}',
            "",
        ]),
        encoding="utf-8",
    )
    print(f"[autostart] Terpasang: {target}")
    print("[autostart] Playlist Studio akan jalan sendiri tiap Windows login.")


def _autostart_linux(command: str, remove: bool):
    """Pakai XDG autostart — dihormati LXQt (Lubuntu), XFCE, GNOME, KDE."""
    target = (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
              / "autostart" / "playliststudio.desktop")
    if remove:
        if target.exists():
            target.unlink()
            print(f"[autostart] Dihapus: {target}")
        else:
            print("[autostart] Tidak ada yang perlu dihapus.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '\n'.join([
            "[Desktop Entry]",
            "Type=Application",
            "Name=Playlist Studio",
            "Comment=Pemutar playlist multi-layar",
            f"Path={BASE_DIR}",
            f"Exec=sh -c {shlex.quote(command)}",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]),
        encoding="utf-8",
    )
    target.chmod(0o755)
    print(f"[autostart] Terpasang: {target}")
    print("[autostart] Playlist Studio akan jalan sendiri tiap login.")


def _reset_db(db):
    if db.DB_PATH.exists():
        backup = db.DB_PATH.with_suffix(".db.bak")
        shutil.copy2(db.DB_PATH, backup)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db.DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        print(f"[db] Database lama dibackup ke {backup} lalu dihapus.")


def main():
    ap = argparse.ArgumentParser(description="Playlist Studio runner")
    ap.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--migrate-only", action="store_true")
    ap.add_argument("--reset-db", action="store_true")
    ap.add_argument("--skip-deps", action="store_true")
    ap.add_argument("--install-autostart", action="store_true",
                    help="jalan otomatis saat login (Windows & Linux)")
    ap.add_argument("--remove-autostart", action="store_true")
    ap.add_argument("--reload", action="store_true", help="auto-reload untuk development")
    args = ap.parse_args()

    print("=" * 62)
    print("  Playlist Studio - multi playlist, multi stream, lokal & privat")
    print("=" * 62)

    # --- 1. Dependency: install yang kurang, skip yang sudah ada.
    #     Versi .exe sudah membawa semuanya, jadi langkah ini dilewati.
    if FROZEN:
        print("[deps] Versi portable - semua sudah dibundel, skip.")
    elif not args.skip_deps and not ensure_deps():
        sys.exit(1)

    # Baru boleh di-import setelah dependency dipastikan ada.
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    from backend import db, launcher

    if args.install_autostart or args.remove_autostart:
        install_autostart(remove=args.remove_autostart)
        return

    if args.reset_db:
        _reset_db(db)

    # --- 2. Database: bikin kalau belum ada, skip kalau sudah terkini.
    db.migrate()

    if args.migrate_only:
        print("[runner] --migrate-only: selesai.")
        return

    # --- 3. Server.
    browser = launcher.find_browser()
    monitors = launcher.list_monitors()
    proxy = (os.getenv("PROXY_SERVER") or "").strip()
    print(f"[env] Browser stream : {browser or 'TIDAK DITEMUKAN (pakai browser default)'}")
    if proxy:
        print(f"[env] Proxy stream   : {proxy} (dipakai semua window)")
    print(f"[env] Monitor terdeteksi: {len(monitors)}")
    for m in monitors:
        print(f"        [{m['index']}] {m['label']}  @ {m['x']},{m['y']}")

    url = f"http://{args.host}:{args.port}/"
    # Dipakai penjadwal saat membuka window tanpa ada request masuk.
    os.environ["APP_BASE_URL"] = url.rstrip("/")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"[runner] GUI  : {url}")
    print("[runner] Ctrl+C untuk berhenti (semua window stream ikut ditutup).")

    import uvicorn

    # Di .exe tidak ada modul yang bisa di-reload dari path, jadi app-nya
    # dioper sebagai objek. Dari source tetap pakai import string agar --reload jalan.
    if FROZEN:
        from backend.main import app as fastapi_app

        target, reload_flag = fastapi_app, False
    else:
        target, reload_flag = "backend.main:app", args.reload

    try:
        uvicorn.run(
            target,
            host=args.host,
            port=args.port,
            reload=reload_flag,
            log_level="warning",
        )
    finally:
        launcher.stop_all()


if __name__ == "__main__":
    main()
