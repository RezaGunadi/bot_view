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
import sysconfig
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


VENV_DIR = BASE_DIR / ".venv"
# Penanda proses anak di dalam .venv — supaya tidak bootstrap berulang tanpa henti.
BOOTSTRAP_ENV = "PLAYLIST_STUDIO_BOOTSTRAPPED"


def _venv_python() -> Path:
    """Interpreter di dalam .venv proyek."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _in_project_venv() -> bool:
    """Apakah interpreter yang sedang jalan ini milik .venv proyek?

    Membandingkan sys.prefix, bukan sys.executable: di Linux .venv/bin/python
    hanyalah symlink ke interpreter sistem, jadi resolve() pada kedua sisi
    menghasilkan path yang sama dan perbandingan executable selalu benar -
    padahal yang jalan python sistem. Di dalam venv, sys.prefix menunjuk ke
    folder venv itu sendiri; di luar, ke prefix sistem.
    """
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def _missing_packages() -> list:
    return [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]


def _has_pip(python: str) -> bool:
    return subprocess.call([python, "-m", "pip", "--version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _try_ensurepip(python: str) -> bool:
    """Coba pulihkan pip di venv yang terlanjur terbentuk tanpa pip."""
    subprocess.call([python, "-m", "ensurepip", "--default-pip"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return _has_pip(python)


def _venv_is_broken() -> bool:
    """.venv-nya ada, tapi tidak bisa dipakai memasang apa pun.

    Terjadi kalau `python -m venv` sempat dijalankan saat paket python3-venv
    belum lengkap: foldernya terbentuk dan bin/python-nya ada, tapi pip tidak
    pernah ikut. Tanpa pemeriksaan ini, run berikutnya melihat bin/python lalu
    masuk ke venv cacat itu dan gagal di tempat yang membingungkan.
    """
    python = _venv_python()
    if not python.exists():
        return False
    return not _has_pip(str(python)) and not _try_ensurepip(str(python))


def _externally_managed() -> bool:
    """PEP 668: Debian/Ubuntu menandai Python sistem sebagai terlarang untuk pip."""
    return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()


def _apt_venv_hint() -> None:
    """Saran yang bisa langsung dijalankan saat modul venv belum lengkap."""
    if not sys.platform.startswith("linux"):
        return
    # Debian menamai paketnya per versi: python3.12-venv, bukan python3-venv saja.
    tag = "python%d.%d" % sys.version_info[:2]
    print("       Paling gampang, jalankan:  bash setup-linux.sh")
    print(f"       Itu memasang {tag}-venv sendiri lalu melanjutkan sampai selesai.")
    print(f"       Kalau mau manual:  sudo apt install {tag}-venv")


def _offer_setup_script() -> None:
    """Tawarkan menjalankan setup-linux.sh - hanya skrip itu yang boleh apt.

    run.py tidak pernah memanggil sudo diam-diam. Pertanyaannya juga cuma
    muncul kalau ada orang di depan terminal yang bisa menjawab; di autostart
    atau lewat pipe, langkah ini dilewati.
    """
    script = BASE_DIR / "setup-linux.sh"
    if not sys.platform.startswith("linux") or not script.exists():
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    print()
    try:
        answer = input(f"[deps] Jalankan {script.name} sekarang? (butuh sudo) [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer.strip().lower() not in ("y", "ya", "yes"):
        return
    print()
    try:
        os.execvp("bash", ["bash", str(script)])
    except OSError as e:
        print(f"[deps] Tidak bisa menjalankan bash: {e}")


def _install_into(python: str, missing: list) -> bool:
    """Pasang paket yang kurang memakai pip milik interpreter `python`."""
    print("[deps] Memasang sekarang (sekali saja, run berikutnya langsung skip)...")
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", *missing]
    if subprocess.call(cmd) != 0:
        print()
        print("[deps] GAGAL memasang dependency.")
        # Di Debian/Ubuntu, menyuruh orang menjalankan pip manual justru
        # menyesatkan: pip-nya memang tidak ada, dan PEP 668 juga menolaknya.
        if sys.platform.startswith("linux"):
            print("       Paling gampang, jalankan:  bash setup-linux.sh")
            print("       Itu memasang semuanya sekali jalan: Python, browser,")
            print("       wmctrl, lalu dependency ke .venv di dalam folder ini.")
        else:
            print("       Coba manual:  " + " ".join(cmd))
        return False

    importlib.invalidate_caches()
    still = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if still:
        print(f"[deps] Masih belum terbaca: {', '.join(still)}. Coba jalankan ulang run.py.")
        return False
    print("[deps] Selesai.")
    return True


def _make_venv() -> bool:
    """Bikin .venv yang lengkap. Yang cacat dibuang dulu."""
    if VENV_DIR.exists():
        if not (VENV_DIR / "pyvenv.cfg").exists():
            print(f"[deps] {VENV_DIR} sudah ada tapi bukan virtualenv.")
            print("       Pindahkan atau hapus folder itu dulu.")
            return False
        print(f"[deps] {VENV_DIR.name} yang lama tidak punya pip - dibuat ulang.")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    print(f"[deps] Membuat {VENV_DIR.name}...")
    rc = subprocess.call([sys.executable, "-m", "venv", str(VENV_DIR)])
    python = _venv_python()
    # rc==0 saja tidak cukup: venv bisa terbentuk setengah jadi, tanpa pip.
    if rc != 0 or not python.exists() or not _has_pip(str(python)):
        print()
        print("[deps] GAGAL membuat virtualenv yang lengkap.")
        _apt_venv_hint()
        _offer_setup_script()
        return False
    return True


def _relaunch_in_venv() -> bool:
    """Pastikan .venv sehat, lalu jalankan ulang run.py di dalamnya.

    Dipakai kalau Python sistem tidak bisa dipasangi paket - kondisi normal di
    Debian/Ubuntu, yang python3-nya datang tanpa pip dan sejak PEP 668 memang
    menolak ditulisi. Tidak perlu sudo, tidak mengotori Python sistem.
    """
    if os.environ.get(BOOTSTRAP_ENV):
        # Sudah pernah dilempar ke .venv tapi tetap kurang - jangan berputar.
        print(f"[deps] Sudah lewat {VENV_DIR.name} tapi dependency masih kurang.")
        print(f"       Hapus folder {VENV_DIR} lalu jalankan lagi.")
        return False

    if not _venv_python().exists() or _venv_is_broken():
        if not _make_venv():
            return False

    python = _venv_python()
    print(f"[deps] Menjalankan ulang lewat {VENV_DIR.name}...")
    env = dict(os.environ)
    env[BOOTSTRAP_ENV] = "1"
    cmd = [str(python), str(BASE_DIR / "run.py"), *sys.argv[1:]]
    if os.name == "posix":
        # Ganti proses ini supaya Ctrl+C tetap langsung mengenai server.
        os.execve(str(python), cmd, env)
    raise SystemExit(subprocess.call(cmd, env=env))


def ensure_deps() -> bool:
    """Install dependency yang belum ada. Yang sudah terpasang dilewati.

    Urutan usaha: pasang langsung ke Python yang sedang jalan; kalau Python itu
    tidak boleh/tidak bisa ditulisi, pindah ke .venv proyek.
    """
    missing = _missing_packages()
    if not missing:
        print(f"[deps] {len(REQUIRED)} dependency sudah terpasang - skip.")
        return True

    print(f"[deps] Kurang {len(missing)}: {', '.join(missing)}")

    # Sudah di dalam .venv proyek - di sinilah tempatnya, tidak ada fallback lagi.
    if _in_project_venv():
        if not _has_pip(sys.executable) and not _try_ensurepip(sys.executable):
            print(f"[deps] {VENV_DIR.name} ini tidak punya pip - venv-nya cacat.")
            print(f"       Hapus dulu:  rm -rf {VENV_DIR}")
            _apt_venv_hint()
            _offer_setup_script()
            return False
        return _install_into(sys.executable, missing)

    if _externally_managed():
        print("[deps] Python sistem ditandai externally-managed (PEP 668).")
    elif not _has_pip(sys.executable):
        print("[deps] Python ini tidak punya pip.")
    elif _install_into(sys.executable, missing):
        return True
    else:
        print("[deps] Gagal memasang langsung, coba lewat .venv...")

    return _relaunch_in_venv()


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

    # Proses induk sudah mencetak banner sebelum melempar ke .venv.
    if not os.environ.get(BOOTSTRAP_ENV):
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
