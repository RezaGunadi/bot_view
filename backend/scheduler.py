"""Penjadwal: nyalakan dan matikan stream otomatis pada jam yang ditentukan.

Cara kerjanya sengaja berbasis **transisi**, bukan "pastikan selalu jalan":
penjadwal hanya bertindak saat jam sekarang baru saja melewati jam mulai atau
jam berhenti. Efeknya, kalau kamu matikan sebuah window secara manual di tengah
jadwal, dia TIDAK dinyalakan lagi sampai jadwal berikutnya — kontrol manual menang.
"""
import asyncio
import os
from datetime import datetime, time as dtime

from . import db, launcher

CHECK_SECONDS = 30
MAX_RESTARTS_PER_HOUR = 5

_last_check: datetime | None = None
_restarts: dict[int, list[datetime]] = {}   # riwayat restart per stream


def base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _parse_hhmm(value: str):
    try:
        hh, mm = value.strip().split(":")
        return dtime(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def _active_today(schedule: dict, day: int) -> bool:
    """day: 1=Senin .. 7=Minggu (isoweekday)."""
    days = [d.strip() for d in (schedule.get("days") or "").split(",") if d.strip()]
    return not days or str(day) in days


def _crossed(mark: dtime, prev: datetime, now: datetime) -> bool:
    """True kalau jam `mark` terlewati di antara `prev` dan `now`."""
    if prev.date() != now.date():
        # ganti hari: anggap semua jam sampai sekarang sudah terlewati
        return mark <= now.time()
    return prev.time() < mark <= now.time()


def _targets(schedule: dict) -> list[dict]:
    streams = db.list_streams()
    if schedule.get("stream_id"):
        return [s for s in streams if s["id"] == schedule["stream_id"]]
    return streams


def _start(stream: dict, monitors) -> str:
    if launcher.is_alive(stream["id"]):
        return "sudah jalan"
    if not stream["playlist_id"] or not db.list_items(stream["playlist_id"]):
        return "playlist kosong"
    launcher.launch_stream(stream, base_url(), monitors=monitors)
    db.update_stream(stream["id"], status="running", last_started=db.now_iso())
    return "dinyalakan"


def _stop(stream: dict) -> str:
    if not launcher.is_alive(stream["id"]):
        # sudah mati duluan; pastikan tidak ikut dinyalakan ulang oleh recover()
        db.update_stream(stream["id"], status="stopped", pid=0)
        return "sudah mati"
    launcher.stop_stream(stream["id"])
    db.update_stream(stream["id"], status="stopped", pid=0)
    return "dimatikan"


def recover(now: datetime) -> list[str]:
    """Nyalakan ulang window yang mati sendiri.

    Yang dihitung "mati sendiri" adalah window yang statusnya masih `crashed` —
    ditandai begitu oleh launcher.reap() saat prosesnya hilang tanpa diminta.
    Stream yang distop lewat panel atau lewat jadwal statusnya `stopped`, jadi
    tidak pernah ikut dinyalakan ulang di sini.

    Ada batas 5 kali per jam supaya window yang rusak terus tidak dinyalakan
    berulang-ulang tanpa henti.
    """
    actions = []
    monitors = None
    for s in db.streams_needing_restart():
        history = [t for t in _restarts.get(s["id"], []) if (now - t).total_seconds() < 3600]
        if len(history) >= MAX_RESTARTS_PER_HOUR:
            db.update_stream(s["id"], status="stopped", pid=0)
            actions.append(f"[pulih] {s['name']}: gagal terus, berhenti dicoba")
            _restarts[s["id"]] = history
            continue
        if not s["playlist_id"] or not db.list_items(s["playlist_id"]):
            db.update_stream(s["id"], status="stopped", pid=0)
            continue
        if monitors is None:
            monitors = launcher.list_monitors()
        launcher.launch_stream(s, base_url(), monitors=monitors)
        db.update_stream(s["id"], status="running", last_started=db.now_iso())
        history.append(now)
        _restarts[s["id"]] = history
        actions.append(f"[pulih] {s['name']}: mati sendiri -> dinyalakan lagi "
                       f"({len(history)}/{MAX_RESTARTS_PER_HOUR} jam ini)")
    return actions


def tick(now: datetime | None = None) -> list[str]:
    """Satu putaran pemeriksaan. Return daftar aksi yang dilakukan (untuk log)."""
    global _last_check
    now = now or datetime.now()
    prev, _last_check = _last_check, now
    if prev is None:
        return []          # putaran pertama cuma menandai waktu

    actions = []
    # Bersihkan window yang prosesnya sudah hilang. Ini juga jalan saat panel
    # kontrol tidak dibuka sama sekali — penting untuk mini PC yang ditinggal.
    for sid in launcher.reap():
        db.update_stream(sid, status="crashed", pid=0)

    monitors = None
    for sch in db.list_schedules():
        if not sch["enabled"] or not _active_today(sch, now.isoweekday()):
            continue
        start, stop = _parse_hhmm(sch["start_time"]), _parse_hhmm(sch["stop_time"])
        if start is None or stop is None:
            continue

        if _crossed(start, prev, now):
            if monitors is None:
                monitors = launcher.list_monitors()
            for s in _targets(sch):
                actions.append(f"[jadwal:{sch['name']}] {s['name']}: {_start(s, monitors)}")
        if _crossed(stop, prev, now):
            for s in _targets(sch):
                actions.append(f"[jadwal:{sch['name']}] {s['name']}: {_stop(s)}")

    actions.extend(recover(now))
    return actions


async def run_forever():
    """Loop latar yang dijalankan bersama server."""
    while True:
        try:
            for line in tick():
                print(line)
        except Exception as e:      # jangan sampai loop mati karena satu error
            print(f"[jadwal] error: {e}")
        await asyncio.sleep(CHECK_SECONDS)
