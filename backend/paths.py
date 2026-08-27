"""Lokasi folder, konsisten baik saat jalan dari source maupun dari .exe.

Saat dibundel PyInstaller ada dua folder yang beda:
  - isi bundel (static/) diekstrak ke folder sementara `sys._MEIPASS` -> read-only
  - data milik user (database, profil browser) harus di SEBELAH exe -> writable

Dipisah di sini supaya modul lain tidak perlu tahu soal itu.
"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
_SRC_ROOT = Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Folder tempat menulis data user (sebelah exe, atau root proyek)."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return _SRC_ROOT


def resource_dir() -> Path:
    """Folder berisi aset read-only (static/)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", str(app_dir())))
    return _SRC_ROOT
