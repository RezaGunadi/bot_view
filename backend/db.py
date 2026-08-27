"""Layer penyimpanan: SQLite lokal + auto-migration.

Filosofi:
  - Semua data ada di satu file `data/playlist.db` (default). Tidak ada server
    database eksternal, tidak ada kredensial, tidak ada data yang keluar dari mesin ini.
  - `migrate()` idempotent: kalau file/tabel belum ada -> dibuat; kalau versinya
    sudah paling baru -> tidak melakukan apa-apa (skip).

Lokasi database bisa dioverride lewat env:
  DATA_DIR  (default: <root proyek>/data)
  DB_PATH   (default: <DATA_DIR>/playlist.db)
"""
import os
import sqlite3
import secrets
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .paths import app_dir

BASE_DIR = app_dir()
DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = Path(os.getenv("DB_PATH") or (DATA_DIR / "playlist.db"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_token(n: int = 8) -> str:
    return secrets.token_hex(n)


# ---------------------------------------------------------------- migrations
# Setiap entri: (versi, [statement SQL...]). JANGAN mengubah migrasi lama —
# tambahkan versi baru di bawahnya supaya database yang sudah jalan tetap aman.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            # Library video global — satu baris per video unik.
            """
            CREATE TABLE videos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                platform   TEXT NOT NULL,
                url        TEXT NOT NULL,
                video_id   TEXT NOT NULL,
                title      TEXT,
                added_at   TEXT NOT NULL,
                play_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE (platform, video_id)
            )
            """,
            # Playlist: banyak playlist, tiap anak bisa dapat playlist sendiri.
            """
            CREATE TABLE playlists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                note       TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            # Isi playlist. Hapus di sini = hapus dari playlist, video tetap ada di library.
            """
            CREATE TABLE playlist_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                video_id    INTEGER NOT NULL REFERENCES videos(id)    ON DELETE CASCADE,
                position    INTEGER NOT NULL DEFAULT 0,
                added_at    TEXT NOT NULL,
                UNIQUE (playlist_id, video_id)
            )
            """,
            "CREATE INDEX idx_items_playlist ON playlist_items(playlist_id, position)",
            # Satu stream = satu window browser yang memutar satu playlist.
            """
            CREATE TABLE streams (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                token         TEXT NOT NULL UNIQUE,
                name          TEXT NOT NULL,
                playlist_id   INTEGER REFERENCES playlists(id) ON DELETE SET NULL,
                mode          TEXT NOT NULL DEFAULT 'sequential',
                timer_seconds INTEGER NOT NULL DEFAULT 60,
                loop_queue    INTEGER NOT NULL DEFAULT 1,
                monitor       INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'stopped',
                pid           INTEGER,
                created_at    TEXT NOT NULL,
                last_started  TEXT
            )
            """,
            # Catatan "hit": satu baris tiap kali sebuah video mulai diputar.
            """
            CREATE TABLE play_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id   INTEGER REFERENCES streams(id) ON DELETE SET NULL,
                playlist_id INTEGER,
                video_id    INTEGER NOT NULL,
                url         TEXT NOT NULL,
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                seconds     INTEGER
            )
            """,
            "CREATE INDEX idx_playlog_video ON play_log(video_id, started_at)",
            "CREATE INDEX idx_playlog_stream ON play_log(stream_id, started_at)",
        ],
    ),
    (
        2,
        [
            # Batas waktu sesi: 0 = tanpa batas. Dipakai supaya playlist tidak
            # berputar semalaman saat tidak ada yang menonton.
            "ALTER TABLE streams ADD COLUMN stop_after_minutes INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        3,
        [
            # Jadwal otomatis: nyalakan/matikan stream pada jam tertentu.
            # stream_id NULL = berlaku untuk semua stream.
            """
            CREATE TABLE schedules (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                stream_id  INTEGER REFERENCES streams(id) ON DELETE CASCADE,
                start_time TEXT NOT NULL,
                stop_time  TEXT NOT NULL,
                days       TEXT NOT NULL DEFAULT '1,2,3,4,5',
                enabled    INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """,
            # Kabar terakhir dari window player: sedang main / terjeda / diam.
            "ALTER TABLE streams ADD COLUMN last_state TEXT",
            "ALTER TABLE streams ADD COLUMN last_seen TEXT",
        ],
    ),
    (
        4,
        [
            # play_count baru dihitung setelah video benar-benar mulai diputar,
            # bukan saat dicoba. Kolom ini menjaga agar tidak dihitung dua kali.
            "ALTER TABLE play_log ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        5,
        [
            # Nyalakan lagi window yang mati sendiri (bukan yang sengaja distop).
            "ALTER TABLE streams ADD COLUMN auto_restart INTEGER NOT NULL DEFAULT 1",
            # Hasil pemeriksaan video: ok / private / dihapus / tidak bisa dicek.
            "ALTER TABLE videos ADD COLUMN status TEXT",
            "ALTER TABLE videos ADD COLUMN checked_at TEXT",
        ],
    ),
    (
        6,
        [
            # Judul video yang sedang diputar tiap window, untuk ditampilkan di panel.
            "ALTER TABLE streams ADD COLUMN last_title TEXT",
        ],
    ),
]

SCHEMA_VERSION = max(v for v, _ in MIGRATIONS)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: beberapa window player bisa baca/tulis berbarengan tanpa saling kunci.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def migrate(verbose: bool = True) -> dict:
    """Buat/naikkan skema seperlunya. Aman dipanggil berkali-kali.

    Return: {"db": path, "from": versi_lama, "to": versi_baru, "applied": [versi...]}
    """
    fresh = not DB_PATH.exists()
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        before = current_version(conn)
        applied = []
        for version, statements in sorted(MIGRATIONS):
            if version <= before:
                continue  # sudah pernah dijalankan -> skip
            for sql in statements:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, now_iso()),
            )
            conn.commit()
            applied.append(version)

        # Sekali saja: sediakan playlist default supaya GUI tidak kosong melompong.
        if applied and before == 0:
            conn.execute(
                "INSERT OR IGNORE INTO playlists (name, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                ("Playlist 1", "Playlist bawaan", now_iso(), now_iso()),
            )
            conn.commit()
    finally:
        conn.close()

    info = {
        "db": str(DB_PATH),
        "fresh": fresh,
        "from": before,
        "to": SCHEMA_VERSION,
        "applied": applied,
    }
    if verbose:
        if applied:
            what = "dibuat baru" if before == 0 else "dinaikkan"
            print(f"[db] Skema {what}: v{before} -> v{SCHEMA_VERSION} ({DB_PATH})")
        else:
            print(f"[db] Skema sudah v{before}, tidak ada migrasi baru — skip. ({DB_PATH})")
    return info


# ------------------------------------------------------------------ helpers
def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _row(cur):
    r = cur.fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------- videos
def list_videos() -> list[dict]:
    conn = connect()
    try:
        return _rows(conn.execute("SELECT * FROM videos ORDER BY id DESC"))
    finally:
        conn.close()


def get_video(vid: int):
    conn = connect()
    try:
        return _row(conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)))
    finally:
        conn.close()


def upsert_video(platform: str, url: str, video_id: str, title=None) -> dict:
    """Simpan video ke library. Kalau (platform, video_id) sudah ada, pakai yang lama."""
    conn = connect()
    try:
        existing = _row(
            conn.execute(
                "SELECT * FROM videos WHERE platform = ? AND video_id = ?",
                (platform, video_id),
            )
        )
        if existing:
            if title and not existing.get("title"):
                conn.execute("UPDATE videos SET title = ? WHERE id = ?", (title, existing["id"]))
                conn.commit()
                existing["title"] = title
            return existing
        cur = conn.execute(
            "INSERT INTO videos (platform, url, video_id, title, added_at) VALUES (?, ?, ?, ?, ?)",
            (platform, url, video_id, title, now_iso()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM videos WHERE id = ?", (cur.lastrowid,)))
    finally:
        conn.close()


def update_video(vid: int, title=None):
    conn = connect()
    try:
        if title is not None:
            conn.execute("UPDATE videos SET title = ? WHERE id = ?", (title, vid))
            conn.commit()
        return _row(conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)))
    finally:
        conn.close()


def delete_video(vid: int) -> bool:
    """Hapus dari library — otomatis hilang juga dari semua playlist (CASCADE)."""
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM videos WHERE id = ?", (vid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------- playlists
def list_playlists() -> list[dict]:
    conn = connect()
    try:
        return _rows(
            conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id = p.id) AS item_count
                FROM playlists p
                ORDER BY p.id ASC
                """
            )
        )
    finally:
        conn.close()


def get_playlist(pid: int):
    conn = connect()
    try:
        return _row(conn.execute("SELECT * FROM playlists WHERE id = ?", (pid,)))
    finally:
        conn.close()


def _unique_name(conn, name: str) -> str:
    """Cari nama yang belum dipakai: 'A', 'A (2)', 'A (3)', ..."""
    candidate, n = name, 1
    while conn.execute("SELECT 1 FROM playlists WHERE name = ?", (candidate,)).fetchone():
        n += 1
        candidate = f"{name} ({n})"
    return candidate


def create_playlist(name: str, note=None) -> dict:
    conn = connect()
    try:
        final = _unique_name(conn, name.strip() or "Playlist")
        cur = conn.execute(
            "INSERT INTO playlists (name, note, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (final, note, now_iso(), now_iso()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM playlists WHERE id = ?", (cur.lastrowid,)))
    finally:
        conn.close()


def rename_playlist(pid: int, name=None, note=None):
    conn = connect()
    try:
        if name is not None:
            current = _row(conn.execute("SELECT name FROM playlists WHERE id = ?", (pid,)))
            if current and current["name"] != name:
                name = _unique_name(conn, name.strip() or "Playlist")
                conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, pid))
        if note is not None:
            conn.execute("UPDATE playlists SET note = ? WHERE id = ?", (note, pid))
        conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (now_iso(), pid))
        conn.commit()
        return _row(conn.execute("SELECT * FROM playlists WHERE id = ?", (pid,)))
    finally:
        conn.close()


def delete_playlist(pid: int) -> bool:
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM playlists WHERE id = ?", (pid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def copy_playlist(pid: int, new_name=None):
    """Duplikat playlist beserta isinya (video tidak diduplikasi, hanya direferensi)."""
    conn = connect()
    try:
        src = _row(conn.execute("SELECT * FROM playlists WHERE id = ?", (pid,)))
        if src is None:
            return None
        base = (new_name or (src["name"] + " - salinan")).strip()
        name = _unique_name(conn, base)
        cur = conn.execute(
            "INSERT INTO playlists (name, note, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, src["note"], now_iso(), now_iso()),
        )
        new_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO playlist_items (playlist_id, video_id, position, added_at)
            SELECT ?, video_id, position, ? FROM playlist_items
            WHERE playlist_id = ? ORDER BY position ASC
            """,
            (new_id, now_iso(), pid),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM playlists WHERE id = ?", (new_id,)))
    finally:
        conn.close()


# ----------------------------------------------------------- playlist items
def list_items(pid: int) -> list[dict]:
    conn = connect()
    try:
        return _rows(
            conn.execute(
                """
                SELECT i.id AS item_id, i.playlist_id, i.position, i.added_at,
                       v.id AS video_id, v.platform, v.url, v.video_id AS ext_id,
                       v.title, v.play_count, v.status, v.checked_at
                FROM playlist_items i
                JOIN videos v ON v.id = i.video_id
                WHERE i.playlist_id = ?
                ORDER BY i.position ASC, i.id ASC
                """,
                (pid,),
            )
        )
    finally:
        conn.close()


def add_item(pid: int, video_pk: int):
    conn = connect()
    try:
        nxt = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM playlist_items WHERE playlist_id = ?",
            (pid,),
        ).fetchone()["n"]
        conn.execute(
            "INSERT OR IGNORE INTO playlist_items (playlist_id, video_id, position, added_at) "
            "VALUES (?, ?, ?, ?)",
            (pid, video_pk, nxt, now_iso()),
        )
        conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (now_iso(), pid))
        conn.commit()
    finally:
        conn.close()
    return list_items(pid)


def remove_item(pid: int, item_id: int) -> bool:
    """Hapus video DARI playlist ini saja - video tetap ada di library & playlist lain."""
    conn = connect()
    try:
        cur = conn.execute(
            "DELETE FROM playlist_items WHERE id = ? AND playlist_id = ?", (item_id, pid)
        )
        conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (now_iso(), pid))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def reorder_items(pid: int, item_ids: list[int]):
    conn = connect()
    try:
        for pos, iid in enumerate(item_ids):
            conn.execute(
                "UPDATE playlist_items SET position = ? WHERE id = ? AND playlist_id = ?",
                (pos, iid, pid),
            )
        conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (now_iso(), pid))
        conn.commit()
    finally:
        conn.close()
    return list_items(pid)


# ------------------------------------------------------------------ streams
def list_streams() -> list[dict]:
    conn = connect()
    try:
        return _rows(
            conn.execute(
                """
                SELECT s.*, p.name AS playlist_name,
                       (SELECT COUNT(*) FROM playlist_items i
                        WHERE i.playlist_id = s.playlist_id) AS item_count
                FROM streams s
                LEFT JOIN playlists p ON p.id = s.playlist_id
                ORDER BY s.id ASC
                """
            )
        )
    finally:
        conn.close()


def get_stream(sid: int):
    conn = connect()
    try:
        return _row(
            conn.execute(
                "SELECT s.*, p.name AS playlist_name FROM streams s "
                "LEFT JOIN playlists p ON p.id = s.playlist_id WHERE s.id = ?",
                (sid,),
            )
        )
    finally:
        conn.close()


def get_stream_by_token(token: str):
    conn = connect()
    try:
        return _row(
            conn.execute(
                "SELECT s.*, p.name AS playlist_name FROM streams s "
                "LEFT JOIN playlists p ON p.id = s.playlist_id WHERE s.token = ?",
                (token,),
            )
        )
    finally:
        conn.close()


def create_stream(name: str, playlist_id=None, mode="sequential", timer_seconds=60,
                  loop_queue=True, monitor=0, stop_after_minutes=0,
                  auto_restart=True) -> dict:
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO streams (token, name, playlist_id, mode, timer_seconds,
                                 loop_queue, monitor, stop_after_minutes, auto_restart,
                                 status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'stopped', ?)
            """,
            (new_token(), name, playlist_id, mode, timer_seconds,
             1 if loop_queue else 0, monitor, stop_after_minutes,
             1 if auto_restart else 0, now_iso()),
        )
        conn.commit()
        sid = cur.lastrowid
    finally:
        conn.close()
    return get_stream(sid)


def update_stream(sid: int, **fields):
    allowed = {"name", "playlist_id", "mode", "timer_seconds", "loop_queue",
               "monitor", "stop_after_minutes", "auto_restart", "status", "pid",
               "last_started"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            # playlist_id boleh dikosongkan lewat nilai 0 -> disimpan sebagai NULL
            if k == "playlist_id" and v == 0:
                v = None
            if k in ("loop_queue", "auto_restart"):
                v = 1 if v else 0
            sets.append(k + " = ?")
            params.append(v)
    if sets:
        conn = connect()
        try:
            params.append(sid)
            conn.execute("UPDATE streams SET " + ", ".join(sets) + " WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
    return get_stream(sid)


def delete_stream(sid: int) -> bool:
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM streams WHERE id = ?", (sid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ----------------------------------------------------------------- play log
def log_play_start(stream_id, playlist_id, video_pk: int, url: str) -> int:
    """Catat satu 'hit': video ini mulai diputar sekarang."""
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO play_log (stream_id, playlist_id, video_id, url, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (stream_id, playlist_id, video_pk, url, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def confirm_play(log_id: int) -> bool:
    """Tandai bahwa video ini benar-benar mulai diputar, lalu naikkan play_count.

    Dipanggil player saat status berubah jadi 'main'. Video yang gagal diputar
    (dihapus, private, mandek) tidak pernah sampai ke sini, jadi tidak ikut dihitung.
    """
    conn = connect()
    try:
        row = _row(conn.execute(
            "SELECT video_id, confirmed FROM play_log WHERE id = ?", (log_id,)))
        if row is None or row["confirmed"]:
            return False
        conn.execute("UPDATE play_log SET confirmed = 1 WHERE id = ?", (log_id,))
        conn.execute("UPDATE videos SET play_count = play_count + 1 WHERE id = ?",
                     (row["video_id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def log_play_end(log_id: int, seconds=None):
    conn = connect()
    try:
        conn.execute(
            "UPDATE play_log SET ended_at = ?, seconds = ? WHERE id = ?",
            (now_iso(), seconds, log_id),
        )
        conn.commit()
    finally:
        conn.close()


def recent_plays(limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        return _rows(
            conn.execute(
                """
                SELECT l.*, v.title, v.platform, s.name AS stream_name
                FROM play_log l
                LEFT JOIN videos v ON v.id = l.video_id
                LEFT JOIN streams s ON s.id = l.stream_id
                ORDER BY l.id DESC LIMIT ?
                """,
                (limit,),
            )
        )
    finally:
        conn.close()


def stats() -> dict:
    conn = connect()
    try:
        def count(table):
            return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

        return {
            "videos": count("videos"),
            "playlists": count("playlists"),
            "streams": count("streams"),
            "plays": count("play_log"),
        }
    finally:
        conn.close()


# ----------------------------------------------------------------- schedules
def list_schedules() -> list[dict]:
    conn = connect()
    try:
        return _rows(
            conn.execute(
                "SELECT c.*, s.name AS stream_name FROM schedules c "
                "LEFT JOIN streams s ON s.id = c.stream_id ORDER BY c.start_time, c.id"
            )
        )
    finally:
        conn.close()


def create_schedule(name: str, start_time: str, stop_time: str,
                    stream_id=None, days: str = "1,2,3,4,5", enabled: bool = True) -> dict:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO schedules (name, stream_id, start_time, stop_time, days,"
            " enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, stream_id, start_time, stop_time, days,
             1 if enabled else 0, now_iso()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM schedules WHERE id = ?", (cur.lastrowid,)))
    finally:
        conn.close()


def update_schedule(sid: int, **fields):
    allowed = {"name", "stream_id", "start_time", "stop_time", "days", "enabled"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            if k == "enabled":
                v = 1 if v else 0
            if k == "stream_id" and v == 0:
                v = None          # 0 dari GUI berarti "semua stream"
            sets.append(k + " = ?")
            params.append(v)
    if sets:
        conn = connect()
        try:
            params.append(sid)
            conn.execute("UPDATE schedules SET " + ", ".join(sets) + " WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
    conn = connect()
    try:
        return _row(conn.execute("SELECT * FROM schedules WHERE id = ?", (sid,)))
    finally:
        conn.close()


def delete_schedule(sid: int) -> bool:
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM schedules WHERE id = ?", (sid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def touch_stream(sid: int, state: str, title=None):
    """Catat kabar terakhir dari window player: keadaan + video yang sedang diputar."""
    conn = connect()
    try:
        conn.execute(
            "UPDATE streams SET last_state = ?, last_seen = ?, last_title = ? WHERE id = ?",
            (state, now_iso(), title, sid))
        conn.commit()
    finally:
        conn.close()


def set_video_status(video_pk: int, status: str, title=None):
    """Simpan hasil pemeriksaan video (ok / private / dihapus / ...)."""
    conn = connect()
    try:
        if title:
            conn.execute(
                "UPDATE videos SET status = ?, checked_at = ?, "
                "title = COALESCE(NULLIF(title, ''), ?) WHERE id = ?",
                (status, now_iso(), title, video_pk),
            )
        else:
            conn.execute("UPDATE videos SET status = ?, checked_at = ? WHERE id = ?",
                         (status, now_iso(), video_pk))
        conn.commit()
    finally:
        conn.close()


def streams_needing_restart() -> list[dict]:
    """Stream yang matinya tidak disengaja dan boleh dinyalakan ulang."""
    conn = connect()
    try:
        return _rows(conn.execute(
            "SELECT * FROM streams WHERE status = 'crashed' AND auto_restart = 1"))
    finally:
        conn.close()
