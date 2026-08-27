"""Bikin PlaylistStudio.exe — satu file, tidak butuh Python di komputer tujuan.

    python build_exe.py

Hasilnya: dist/PlaylistStudio.exe. Copy file itu ke komputer anak, klik dua kali,
selesai. Database dan profil browser dibuat di folder yang sama dengan exe-nya.
"""
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SEP = ";" if sys.platform == "win32" else ":"


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print("[build] PyInstaller sudah ada - skip.")
    except ImportError:
        print("[build] Memasang PyInstaller...")
        if subprocess.call([sys.executable, "-m", "pip", "install",
                            "--disable-pip-version-check", "pyinstaller"]) != 0:
            sys.exit("[build] Gagal memasang PyInstaller.")


def main():
    ensure_pyinstaller()
    for folder in ("build", "dist"):
        shutil.rmtree(BASE / folder, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "PlaylistStudio",
        "--add-data", f"{BASE / 'static'}{SEP}static",
        # uvicorn memuat sebagian modulnya lewat string, jadi harus disebut manual.
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        # dipakai lewat import di dalam fungsi / oleh starlette
        "--hidden-import", "openpyxl",
        "--hidden-import", "multipart",
        "--hidden-import", "python_multipart",
        "--collect-submodules", "openpyxl",
        "--collect-submodules", "backend",
        "--noconfirm",
        str(BASE / "run.py"),
    ]
    print("[build] Membangun... (beberapa menit untuk pertama kali)")
    if subprocess.call(cmd) != 0:
        sys.exit("[build] Build gagal.")

    exe = BASE / "dist" / ("PlaylistStudio.exe" if sys.platform == "win32" else "PlaylistStudio")
    size = exe.stat().st_size / 1_048_576
    print(f"\n[build] Selesai: {exe}  ({size:.1f} MB)")
    print("[build] Copy file itu ke komputer anak, klik dua kali. Tidak perlu Python.")


if __name__ == "__main__":
    main()
