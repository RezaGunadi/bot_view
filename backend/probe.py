"""Periksa apakah sebuah video masih bisa diputar, sekalian ambil judul aslinya.

Dipakai untuk dua hal:
  1. Menemukan video mati (dihapus/private) SEBELUM jam tayang, bukan pas anak-anak
     sudah duduk di depan layar.
  2. Mengisi judul otomatis, supaya daftar playlist tidak berisi URL panjang.

Memakai endpoint oEmbed publik masing-masing platform — tanpa API key, tanpa login.
Hanya YouTube dan TikTok yang menyediakannya secara terbuka; Facebook dan Instagram
butuh token aplikasi, jadi ditandai "tidak bisa dicek".
"""
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 8
_UA = "Mozilla/5.0 (compatible; PlaylistStudio/1.0)"

OEMBED = {
    "youtube": "https://www.youtube.com/oembed?format=json&url=",
    "tiktok": "https://www.tiktok.com/oembed?url=",
}


def probe(platform: str, url: str) -> dict:
    """Return {status, title}.

    status: ok | dihapus | private | tidak bisa diputar | tidak bisa dicek | gagal cek
    """
    base = OEMBED.get(platform)
    if base is None:
        return {"status": "tidak bisa dicek", "title": None}

    req = urllib.request.Request(base + urllib.parse.quote(url, safe=""),
                                 headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            data = json.loads(res.read().decode("utf-8", "replace"))
        return {"status": "ok", "title": (data.get("title") or "").strip() or None}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "dihapus", "title": None}
        if e.code in (401, 403):
            return {"status": "private", "title": None}
        return {"status": "tidak bisa diputar", "title": None}
    except Exception:
        # jaringan mati / timeout -> jangan sampai video sehat ikut ditandai rusak
        return {"status": "gagal cek", "title": None}


def probe_items(items: list[dict]) -> list[dict]:
    """Periksa banyak item sekaligus. Return ringkasan per item."""
    from concurrent.futures import ThreadPoolExecutor

    def one(it):
        r = probe(it["platform"], it["url"])
        return {"video_id": it["video_id"], "platform": it["platform"],
                "url": it["url"], **r}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, items))
