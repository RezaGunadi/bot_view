"""Deteksi platform dan ekstraksi id/kode video dari sebuah URL.

Fungsi utama: parse(url) -> dict {platform, video_id, embed_url}.
Melempar ValueError kalau URL tidak dikenali.
"""
import re
from urllib.parse import quote

# Regex per platform. Setiap entri: (nama_platform, [pattern...]).
_YOUTUBE_PATTERNS = [
    r"(?:youtube\.com/watch\?[^ ]*\bv=)([A-Za-z0-9_-]{11})",
    r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
    r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
    r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    r"(?:youtube\.com/live/)([A-Za-z0-9_-]{11})",
]

_TIKTOK_PATTERNS = [
    r"tiktok\.com/@[^/]+/video/(\d+)",
    r"tiktok\.com/v/(\d+)",
]

_INSTAGRAM_PATTERNS = [
    r"instagram\.com/reel/([A-Za-z0-9_-]+)",
    r"instagram\.com/reels/([A-Za-z0-9_-]+)",
    r"instagram\.com/p/([A-Za-z0-9_-]+)",
    r"instagram\.com/tv/([A-Za-z0-9_-]+)",
]

_FACEBOOK_PATTERNS = [
    r"facebook\.com/watch/?\?[^ ]*\bv=(\d+)",
    r"facebook\.com/[^/]+/videos/(?:[^/]+/)?(\d+)",
    r"facebook\.com/reel/(\d+)",
    r"facebook\.com/[^/]+/videos/(\d+)",
    r"fb\.watch/([A-Za-z0-9_-]+)",
]


def _first_match(patterns, url):
    for pat in patterns:
        m = re.search(pat, url, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def parse(url: str) -> dict:
    """Kembalikan {platform, video_id, embed_url} dari sebuah URL video.

    Untuk Facebook, video_id yang disimpan adalah URL asli (di-encode saat
    build embed) karena plugin video.php menerima href, bukan sekadar id.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL kosong")
    url = url.strip()

    vid = _first_match(_YOUTUBE_PATTERNS, url)
    if vid:
        return {
            "platform": "youtube",
            "video_id": vid,
            "embed_url": f"https://www.youtube-nocookie.com/embed/{vid}"
                          "?enablejsapi=1&autoplay=1&rel=0&modestbranding=1&playsinline=1",
        }

    vid = _first_match(_TIKTOK_PATTERNS, url)
    if vid:
        return {
            "platform": "tiktok",
            "video_id": vid,
            "embed_url": f"https://www.tiktok.com/embed/v2/{vid}",
        }

    vid = _first_match(_INSTAGRAM_PATTERNS, url)
    if vid:
        return {
            "platform": "instagram",
            "video_id": vid,
            "embed_url": f"https://www.instagram.com/p/{vid}/embed",
        }

    if re.search(r"facebook\.com|fb\.watch", url, re.IGNORECASE):
        # Facebook: plugin video.php butuh URL asli sebagai href.
        vid = _first_match(_FACEBOOK_PATTERNS, url) or url
        return {
            "platform": "facebook",
            "video_id": str(vid),
            "embed_url": (
                "https://www.facebook.com/plugins/video.php"
                f"?href={quote(url, safe='')}&autoplay=true"
            ),
        }

    raise ValueError(f"URL tidak dikenali (bukan YouTube/TikTok/Instagram/Facebook): {url}")


def build_embed_url(platform: str, video_id: str, url: str) -> str:
    """Bangun ulang embed_url dari data tersimpan (dipakai saat serve list)."""
    if platform == "youtube":
        return (
            f"https://www.youtube-nocookie.com/embed/{video_id}"
            "?enablejsapi=1&autoplay=1&rel=0&modestbranding=1&playsinline=1"
        )
    if platform == "tiktok":
        return f"https://www.tiktok.com/embed/v2/{video_id}"
    if platform == "instagram":
        return f"https://www.instagram.com/p/{video_id}/embed"
    if platform == "facebook":
        return (
            "https://www.facebook.com/plugins/video.php"
            f"?href={quote(url, safe='')}&autoplay=true"
        )
    raise ValueError(f"platform tidak dikenal: {platform}")


def canonical_url(platform: str, video_id: str, url: str) -> str:
    """URL asli video (yang di-"hit" tiap kali diputar), dinormalkan bila mungkin."""
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={video_id}"
    if platform == "tiktok":
        return url
    if platform == "instagram":
        return f"https://www.instagram.com/p/{video_id}/"
    return url
