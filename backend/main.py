"""FastAPI app: REST API playlist/stream + serve GUI.

Semua endpoint hanya dilayani di localhost (lihat run.py). Tidak ada data yang
dikirim ke mana pun kecuali ke platform video itu sendiri saat embed diputar.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, launcher, parsers, probe, scheduler, sheets

from .paths import app_dir, resource_dir

BASE_DIR = app_dir()
STATIC_DIR = resource_dir() / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runner sudah memigrasi, tapi kalau uvicorn dijalankan langsung tetap aman.
    db.migrate(verbose=False)
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()
    launcher.stop_all()


app = FastAPI(title="Playlist Studio", lifespan=lifespan)


# ------------------------------------------------------------------ schemas
class VideoIn(BaseModel):
    url: str
    title: str | None = None
    playlist_id: int | None = None


class TitleIn(BaseModel):
    title: str | None = None


class PlaylistIn(BaseModel):
    name: str
    note: str | None = None


class PlaylistPatch(BaseModel):
    name: str | None = None
    note: str | None = None


class CopyIn(BaseModel):
    name: str | None = None


class ItemIn(BaseModel):
    video_id: int | None = None
    url: str | None = None
    title: str | None = None


class ReorderIn(BaseModel):
    order: list[int]


class StreamIn(BaseModel):
    name: str
    playlist_id: int | None = None
    mode: str = "sequential"
    timer_seconds: int = 60
    loop_queue: bool = True
    monitor: int = 0
    stop_after_minutes: int = 0
    auto_restart: bool = True


class StreamPatch(BaseModel):
    name: str | None = None
    playlist_id: int | None = None
    mode: str | None = None
    timer_seconds: int | None = None
    loop_queue: bool | None = None
    monitor: int | None = None
    stop_after_minutes: int | None = None
    auto_restart: bool | None = None


class ScheduleIn(BaseModel):
    name: str
    start_time: str
    stop_time: str
    stream_id: int | None = None
    days: str = "1,2,3,4,5"
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    stream_id: int | None = None
    days: str | None = None
    enabled: bool | None = None


class HeartbeatIn(BaseModel):
    state: str
    title: str | None = None


class HitIn(BaseModel):
    video_id: int


class HitEndIn(BaseModel):
    seconds: int | None = None


def _decorate(row: dict, ext_key: str = "video_id") -> dict:
    """Lengkapi baris video/item dengan embed_url + URL asli yang di-hit.

    `ext_key` menunjuk kolom id eksternal: "video_id" untuk baris tabel videos,
    "ext_id" untuk baris hasil join playlist_items.
    """
    out = dict(row)
    ext = str(out[ext_key])
    out["embed_url"] = parsers.build_embed_url(out["platform"], ext, out["url"])
    out["hit_url"] = parsers.canonical_url(out["platform"], ext, out["url"])
    return out


# ------------------------------------------------------------- API: library
@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/videos")
def api_videos():
    return [_decorate(v) for v in db.list_videos()]


@app.post("/api/videos", status_code=201)
def api_add_video(payload: VideoIn):
    """Tambah video ke library. Kalau `playlist_id` diisi, sekalian masuk playlist itu."""
    try:
        parsed = parsers.parse(payload.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    video = db.upsert_video(
        platform=parsed["platform"],
        url=payload.url.strip(),
        video_id=parsed["video_id"],
        title=(payload.title or None),
    )
    if payload.playlist_id:
        if db.get_playlist(payload.playlist_id) is None:
            raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")
        db.add_item(payload.playlist_id, video["id"])
    return _decorate(video)


@app.put("/api/videos/{video_id}")
def api_edit_video(video_id: int, payload: TitleIn):
    if db.get_video(video_id) is None:
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")
    return _decorate(db.update_video(video_id, title=payload.title))


@app.delete("/api/videos/{video_id}", status_code=204)
def api_delete_video(video_id: int):
    """Hapus dari library (ikut hilang dari semua playlist)."""
    if not db.delete_video(video_id):
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")


@app.get("/api/plays")
def api_plays(limit: int = 50):
    return db.recent_plays(limit)


# ----------------------------------------------------------- API: playlists
@app.get("/api/playlists")
def api_playlists():
    return db.list_playlists()


@app.post("/api/playlists", status_code=201)
def api_create_playlist(payload: PlaylistIn):
    return db.create_playlist(payload.name, payload.note)


@app.put("/api/playlists/{pid}")
def api_patch_playlist(pid: int, payload: PlaylistPatch):
    if db.get_playlist(pid) is None:
        raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")
    return db.rename_playlist(pid, name=payload.name, note=payload.note)


@app.delete("/api/playlists/{pid}", status_code=204)
def api_delete_playlist(pid: int):
    if not db.delete_playlist(pid):
        raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")


@app.post("/api/playlists/{pid}/copy", status_code=201)
def api_copy_playlist(pid: int, payload: CopyIn):
    """Duplikat playlist + seluruh isinya jadi playlist baru."""
    copied = db.copy_playlist(pid, payload.name)
    if copied is None:
        raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")
    return copied


# --------------------------------------------------------------- API: items
@app.get("/api/playlists/{pid}/items")
def api_items(pid: int):
    if db.get_playlist(pid) is None:
        raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")
    return [_decorate(i, "ext_id") for i in db.list_items(pid)]


@app.post("/api/playlists/{pid}/items", status_code=201)
def api_add_item(pid: int, payload: ItemIn):
    """Masukkan video ke playlist: lewat `video_id` (dari library) atau `url` baru."""
    if db.get_playlist(pid) is None:
        raise HTTPException(status_code=404, detail="Playlist tidak ditemukan")
    if payload.video_id:
        if db.get_video(payload.video_id) is None:
            raise HTTPException(status_code=404, detail="Video tidak ditemukan")
        video_pk = payload.video_id
    elif payload.url:
        try:
            parsed = parsers.parse(payload.url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        video_pk = db.upsert_video(
            parsed["platform"], payload.url.strip(), parsed["video_id"], payload.title
        )["id"]
    else:
        raise HTTPException(status_code=400, detail="Butuh `url` atau `video_id`")
    db.add_item(pid, video_pk)
    return [_decorate(i, "ext_id") for i in db.list_items(pid)]


@app.delete("/api/playlists/{pid}/items/{item_id}", status_code=204)
def api_remove_item(pid: int, item_id: int):
    """Hapus video dari playlist ini saja; video tetap ada di library."""
    if not db.remove_item(pid, item_id):
        raise HTTPException(status_code=404, detail="Item tidak ada di playlist ini")


@app.post("/api/playlists/{pid}/check")
def api_check_playlist(pid: int):
    """Periksa semua video di playlist: masih bisa diputar? judul aslinya apa?

    Dijalankan sebelum jam tayang supaya video mati ketahuan lebih dulu.
    """
    items = db.list_items(pid)
    if not items:
        return {"checked": 0, "broken": [], "items": []}
    results = probe.probe_items(items)
    for r in results:
        db.set_video_status(r["video_id"], r["status"], r.get("title"))
    broken = [r for r in results if r["status"] in ("dihapus", "private", "tidak bisa diputar")]
    return {
        "checked": len(results),
        "broken": [b["url"] for b in broken],
        "items": [_decorate(i, "ext_id") for i in db.list_items(pid)],
    }


@app.post("/api/playlists/{pid}/items/reorder")
def api_reorder_items(pid: int, payload: ReorderIn):
    return [_decorate(i, "ext_id") for i in db.reorder_items(pid, payload.order)]


# ------------------------------------------------------------- API: streams
def _stream_view(s: dict, monitors=None) -> dict:
    out = dict(s)
    out["running"] = launcher.is_alive(s["id"])
    r = launcher.resolve_monitor(s.get("monitor"), monitors)
    # Monitor yang tersimpan vs yang benar-benar dipakai sekarang.
    out["monitor_missing"] = r["missing"]
    out["monitor_effective"] = r["index"]
    out["monitor_label"] = r["monitor"]["label"]
    out["monitor_total"] = r["total"]
    return out


@app.get("/api/monitors")
def api_monitors():
    info = launcher.browser_info()
    return {
        "monitors": launcher.list_monitors(),
        "browser": info["path"] if info else None,
        "browser_name": info["name"] if info else None,
        "browser_family": info["family"] if info else None,
        "placement": launcher.placement_status(),
    }


@app.get("/api/streams")
def api_streams():
    # Window yang mati tanpa diminta: tandai 'crashed' + buang profilnya.
    # Penjadwal yang memutuskan apakah dinyalakan ulang (lihat scheduler.recover).
    for sid in launcher.reap():
        db.update_stream(sid, status="crashed", pid=0)
    # Enumerasi monitor sekali saja untuk seluruh daftar.
    monitors = launcher.list_monitors()
    return [_stream_view(s, monitors) for s in db.list_streams()]


@app.post("/api/streams", status_code=201)
def api_create_stream(payload: StreamIn):
    s = db.create_stream(
        name=payload.name.strip() or "Stream",
        playlist_id=payload.playlist_id,
        mode=payload.mode,
        timer_seconds=payload.timer_seconds,
        loop_queue=payload.loop_queue,
        monitor=payload.monitor,
        stop_after_minutes=payload.stop_after_minutes,
        auto_restart=payload.auto_restart,
    )
    return _stream_view(s)


@app.put("/api/streams/{sid}")
def api_patch_stream(sid: int, payload: StreamPatch):
    if db.get_stream(sid) is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    return _stream_view(db.update_stream(sid, **payload.model_dump(exclude_none=True)))


@app.delete("/api/streams/{sid}", status_code=204)
def api_delete_stream(sid: int):
    launcher.stop_stream(sid)
    if not db.delete_stream(sid):
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.post("/api/streams/{sid}/start")
def api_start_stream(sid: int, request: Request, fullscreen: bool = False):
    """Buka window browser terpisah untuk stream ini di monitor pilihannya."""
    s = db.get_stream(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    if not s["playlist_id"]:
        raise HTTPException(status_code=400, detail="Stream ini belum dipasangi playlist")
    if not db.list_items(s["playlist_id"]):
        raise HTTPException(status_code=400, detail="Playlist-nya masih kosong")
    if launcher.is_alive(sid):
        raise HTTPException(status_code=409, detail="Stream ini sudah jalan")

    info = launcher.launch_stream(s, _base_url(request), fullscreen=fullscreen)
    db.update_stream(sid, status="running", pid=info.get("pid"), last_started=db.now_iso())
    return {"stream": _stream_view(db.get_stream(sid)), **info}


@app.post("/api/streams/{sid}/stop")
def api_stop_stream(sid: int):
    stopped = launcher.stop_stream(sid)
    db.update_stream(sid, status="stopped", pid=0)
    return {"stopped": stopped, "stream": _stream_view(db.get_stream(sid))}


@app.post("/api/streams/start-all")
def api_start_all(request: Request, fullscreen: bool = False):
    """Nyalakan semua stream sekaligus — tiap anak langsung dapat window & monitornya."""
    base, monitors, results = _base_url(request), launcher.list_monitors(), []
    for s in db.list_streams():
        if launcher.is_alive(s["id"]):
            results.append({"id": s["id"], "name": s["name"], "skipped": "sudah jalan"})
            continue
        if not s["playlist_id"] or not db.list_items(s["playlist_id"]):
            results.append({"id": s["id"], "name": s["name"], "skipped": "playlist kosong"})
            continue
        info = launcher.launch_stream(s, base, monitors=monitors, fullscreen=fullscreen)
        db.update_stream(s["id"], status="running", pid=info.get("pid"),
                         last_started=db.now_iso())
        results.append({"id": s["id"], "name": s["name"], **info})
    return {"results": results}


@app.post("/api/streams/reassign-monitors")
def api_reassign_monitors():
    """Pindahkan permanen semua stream yang monitornya hilang ke monitor yang ada.

    Dipakai kalau monitor memang tidak akan dipasang lagi. Kalau cuma mati
    sementara, tidak perlu — stream otomatis jatuh ke monitor yang ada dan
    kembali sendiri begitu monitornya nyala.
    """
    monitors = launcher.list_monitors()
    dipindah = []
    for s in db.list_streams():
        r = launcher.resolve_monitor(s.get("monitor"), monitors)
        if r["missing"]:
            db.update_stream(s["id"], monitor=r["index"])
            dipindah.append({"name": s["name"], "dari": r["wanted"] + 1,
                             "ke": r["index"] + 1})
    return {"dipindah": dipindah, "monitor_tersedia": len(monitors)}


@app.post("/api/streams/stop-all")
def api_stop_all():
    for s in db.list_streams():
        launcher.stop_stream(s["id"])
        db.update_stream(s["id"], status="stopped", pid=0)
    return {"ok": True}


# ------------------------------------------------------- API: impor Excel
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/template")
def api_template():
    """Unduh template untuk diisi di Excel."""
    data = sheets.build_template_xlsx()
    if data is not None:
        return Response(
            content=data, media_type=XLSX_MIME,
            headers={"Content-Disposition":
                     'attachment; filename="template-playlist.xlsx"'},
        )
    return Response(
        content=sheets.build_template_csv(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="template-playlist.csv"'},
    )


@app.post("/api/import")
async def api_import(file: UploadFile = File(...), playlist_id: int | None = None):
    """Impor isi file Excel/CSV.

    Kolom `playlist` menentukan playlist tujuan (dibuat otomatis kalau belum ada).
    Baris tanpa kolom itu masuk ke `playlist_id` yang dikirim, atau ke playlist
    pertama kalau tidak ada.
    """
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=400, detail="File terlalu besar (maks 5 MB).")
    try:
        rows = sheets.parse(file.filename or "", raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not rows:
        raise HTTPException(status_code=400, detail="Tidak ada baris berisi url.")

    # Peta nama playlist -> id, supaya nama yang sama tidak dibuat dua kali.
    by_name = {p["name"].strip().lower(): p["id"] for p in db.list_playlists()}
    fallback = playlist_id
    if fallback is None:
        existing = db.list_playlists()
        fallback = existing[0]["id"] if existing else db.create_playlist("Playlist 1")["id"]

    added, gagal, dibuat = 0, [], []
    for row in rows:
        name = row["playlist"].strip()
        if name:
            key = name.lower()
            if key not in by_name:
                created = db.create_playlist(name)
                by_name[key] = created["id"]
                dibuat.append(created["name"])
            target = by_name[key]
        else:
            target = fallback

        try:
            parsed = parsers.parse(row["url"])
        except ValueError:
            gagal.append({"baris": row["baris"], "url": row["url"],
                          "sebab": "link tidak dikenali"})
            continue
        video = db.upsert_video(parsed["platform"], row["url"].strip(),
                                parsed["video_id"], row["judul"] or None)
        db.add_item(target, video["id"])
        added += 1

    return {"ditambahkan": added, "playlist_baru": dibuat,
            "gagal": gagal, "total_baris": len(rows)}


# ------------------------------------------------------------ API: jadwal
@app.get("/api/schedules")
def api_schedules():
    return db.list_schedules()


@app.post("/api/schedules", status_code=201)
def api_create_schedule(payload: ScheduleIn):
    return db.create_schedule(
        name=payload.name.strip() or "Jadwal",
        start_time=payload.start_time,
        stop_time=payload.stop_time,
        stream_id=payload.stream_id or None,
        days=payload.days,
        enabled=payload.enabled,
    )


@app.put("/api/schedules/{sid}")
def api_patch_schedule(sid: int, payload: SchedulePatch):
    return db.update_schedule(sid, **payload.model_dump(exclude_none=True))


@app.delete("/api/schedules/{sid}", status_code=204)
def api_delete_schedule(sid: int):
    if not db.delete_schedule(sid):
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan")


# -------------------------------------------------------------- API: player
@app.get("/api/player/{token}")
def api_player_config(token: str):
    """Konfigurasi + antrian untuk satu window player."""
    s = db.get_stream_by_token(token)
    if s is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    items = db.list_items(s["playlist_id"]) if s["playlist_id"] else []
    return {"stream": s, "items": [_decorate(i, "ext_id") for i in items]}


@app.post("/api/player/{token}/hit", status_code=201)
def api_hit(token: str, payload: HitIn):
    """Dipanggil player tiap kali sebuah video MULAI diputar (satu hit = satu view)."""
    s = db.get_stream_by_token(token)
    if s is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    v = db.get_video(payload.video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")
    hit_url = parsers.canonical_url(v["platform"], v["video_id"], v["url"])
    log_id = db.log_play_start(s["id"], s["playlist_id"], v["id"], hit_url)
    return {"log_id": log_id, "hit_url": hit_url}


@app.post("/api/player/{token}/hit/{log_id}/confirm")
def api_hit_confirm(token: str, log_id: int):
    """Video benar-benar mulai diputar — baru di sini play_count dinaikkan."""
    if db.get_stream_by_token(token) is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    return {"counted": db.confirm_play(log_id)}


@app.post("/api/player/{token}/heartbeat")
def api_heartbeat(token: str, payload: HeartbeatIn):
    """Kabar berkala dari window player: sedang main, terjeda, atau selesai."""
    s = db.get_stream_by_token(token)
    if s is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    db.touch_stream(s["id"], payload.state, payload.title)
    return {"ok": True}


@app.post("/api/player/{token}/hit/{log_id}/end")
def api_hit_end(token: str, log_id: int, payload: HitEndIn):
    db.log_play_end(log_id, payload.seconds)
    return {"ok": True}


# --------------------------------------------------------- static / halaman
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/player/{token}")
def player_page(token: str):
    if db.get_stream_by_token(token) is None:
        raise HTTPException(status_code=404, detail="Stream tidak ditemukan")
    return FileResponse(STATIC_DIR / "player.html")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
