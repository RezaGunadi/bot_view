"""Buka window browser terpisah per stream, di monitor yang dipilih.

Dua hal yang dikerjakan modul ini:

1. **Isolasi / privasi.** Tiap stream dijalankan dengan `--user-data-dir` sendiri
   (folder `data/profiles/stream-<token>`). Artinya: tidak ada akun yang login,
   cookie/history tidak nyampur dengan browser harianmu, dan bisa dihapus otomatis
   saat window ditutup (`WIPE_PROFILE_ON_STOP=1`).

2. **Multi-monitor.** Window dibuka dengan `--window-position` sesuai koordinat
   monitor yang dipilih, jadi stream 1 langsung nongol di monitor utama, stream 2
   di monitor kedua, dst — tanpa perlu digeser manual.

Browser dicari otomatis (Chrome -> Edge -> Brave -> Chromium). Override lewat env
`BROWSER_PATH`.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .paths import app_dir

BASE_DIR = app_dir()
DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE_DIR / "data"))
PROFILE_ROOT = DATA_DIR / "profiles"

# Window yang sedang jalan:
#   {stream_id: {"proc": Popen, "profile": Path, "monitor": index efektif}}
_running: dict[int, dict] = {}


# --------------------------------------------------------------- cari browser
# Urutan pencarian. Chromium duluan karena penempatan window-nya paling rapi,
# tapi Firefox tetap didukung penuh (lihat _launch_firefox).
_WIN_CANDIDATES = [
    ("chromium", r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    ("chromium", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    ("chromium", r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ("chromium", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ("chromium", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ("chromium", r"%ProgramFiles%\BraveSoftware\Brave-Browser\Applicationrave.exe"),
    ("chromium", r"%LocalAppData%\Chromium\Application\chrome.exe"),
    ("firefox", r"%ProgramFiles%\Mozilla Firefoxirefox.exe"),
    ("firefox", r"%ProgramFiles(x86)%\Mozilla Firefoxirefox.exe"),
    ("firefox", r"%LocalAppData%\Mozilla Firefoxirefox.exe"),
]
_POSIX_CANDIDATES = [
    ("chromium", "google-chrome"), ("chromium", "google-chrome-stable"),
    ("chromium", "chromium"), ("chromium", "chromium-browser"),
    ("chromium", "brave-browser"), ("chromium", "microsoft-edge"),
    ("firefox", "firefox"),
    ("chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("firefox", "/Applications/Firefox.app/Contents/MacOS/firefox"),
]


def _family_of(path: str) -> str:
    return "firefox" if "firefox" in Path(path).name.lower() else "chromium"


def browser_info() -> dict | None:
    """Browser yang dipakai untuk window stream: {path, family, name}."""
    override = os.getenv("BROWSER_PATH")
    if override and Path(override).exists():
        return {"path": override, "family": _family_of(override),
                "name": Path(override).name}

    candidates = _WIN_CANDIDATES if sys.platform == "win32" else _POSIX_CANDIDATES
    for family, cand in candidates:
        if sys.platform == "win32":
            p = Path(os.path.expandvars(cand))
            found = str(p) if p.exists() else None
        elif "/" in cand:
            found = cand if Path(cand).exists() else None
        else:
            found = shutil.which(cand)
        if found:
            return {"path": found, "family": family, "name": Path(found).name}
    return None


def find_browser() -> str | None:
    info = browser_info()
    return info["path"] if info else None


# ------------------------------------------------------------------ monitors
def _default_monitor() -> dict:
    return {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
            "full": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "primary": True, "label": "Monitor 1 (default)"}


def list_monitors() -> list[dict]:
    """Daftar monitor + koordinatnya.

    Windows: WinAPI EnumDisplayMonitors. Linux/X11: baca keluaran `xrandr`.
    Kalau gagal, kembalikan satu monitor default supaya aplikasi tetap jalan.
    """
    try:
        mons = _win_monitors() if sys.platform == "win32" else _x11_monitors()
        if mons:
            return mons
    except Exception as e:  # jangan sampai GUI mati cuma karena enumerasi gagal
        print(f"[launcher] gagal enumerasi monitor: {e}")
    return [_default_monitor()]


def _parse_listmonitors(text: str) -> list[dict]:
    """Baca keluaran `xrandr --listmonitors`.

        Monitors: 2
         0: +*HDMI-1 1920/509x1080/286+0+0  HDMI-1
         1: +DP-1 1920/509x1080/286+1920+0  DP-1
    """
    monitors = []
    pattern = re.compile(
        r"^\s*(\d+):\s+\+(?P<primary>\*?)(?P<name>\S+)\s+"
        r"(?P<w>\d+)/\d+x(?P<h>\d+)/\d+\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
    )
    for line in text.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        w, h = int(m.group("w")), int(m.group("h"))
        x, y = int(m.group("x")), int(m.group("y"))
        monitors.append({
            "index": len(monitors), "x": x, "y": y, "width": w, "height": h,
            "full": {"x": x, "y": y, "width": w, "height": h},
            "primary": bool(m.group("primary")),
            "name": m.group("name").lstrip("+*"),
        })
    monitors.sort(key=lambda mo: (not mo["primary"], mo["x"], mo["y"]))
    for i, mo in enumerate(monitors):
        mo["index"] = i
        mo["label"] = (f"Monitor {i + 1} - {mo['name']} {mo['width']}x{mo['height']}"
                       + (" (utama)" if mo["primary"] else ""))
    return monitors


def _x11_monitors() -> list[dict]:
    out = subprocess.run(["xrandr", "--listmonitors"],
                         capture_output=True, text=True, timeout=5)
    return _parse_listmonitors(out.stdout)


def _win_monitors() -> list[dict]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # koordinat fisik, bukan yang di-scale
    except Exception:
        pass

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    monitors: list[dict] = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulonglong, ctypes.c_ulonglong,
        ctypes.POINTER(RECT), ctypes.c_double
    )

    def _cb(hmon, hdc, lprc, data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(ctypes.c_ulonglong(hmon), ctypes.byref(info)):
            r, f = info.rcWork, info.rcMonitor
            primary = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY
            monitors.append({
                "index": len(monitors),
                # rcWork = area kerja (tanpa taskbar); rcMonitor = layar penuh.
                "x": r.left, "y": r.top,
                "width": r.right - r.left, "height": r.bottom - r.top,
                "full": {"x": f.left, "y": f.top,
                         "width": f.right - f.left, "height": f.bottom - f.top},
                "primary": primary,
            })
        return 1

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
    monitors.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    for i, m in enumerate(monitors):
        m["index"] = i
        m["label"] = (
            f"Monitor {i + 1} - {m['width']}x{m['height']}"
            + (" (utama)" if m["primary"] else "")
        )
    return monitors or [_default_monitor()]


# ------------------------------------------------------------------ firefox
def _parse_proxy(proxy: str):
    """'socks5://127.0.0.1:1080' -> ('socks5', '127.0.0.1', 1080). None kalau tak jelas."""
    m = re.match(r"^(?:(socks5|socks4|socks|https?)://)?([^:/]+):(\d+)$", proxy.strip())
    if not m:
        return None
    scheme = (m.group(1) or "http").lower()
    return scheme, m.group(2), int(m.group(3))


def _firefox_user_js(proxy: str = "") -> str:
    """Isi user.js: matikan telemetri/first-run, izinkan autoplay, aktifkan proteksi."""
    prefs = {
        "browser.shell.checkDefaultBrowser": "false",
        "browser.startup.homepage_override.mstone": '"ignore"',
        "browser.aboutwelcome.enabled": "false",
        "browser.messaging-system.whatsNewPanel.enabled": "false",
        "datareporting.policy.dataSubmissionEnabled": "false",
        "datareporting.healthreport.uploadEnabled": "false",
        "toolkit.telemetry.enabled": "false",
        "toolkit.telemetry.unified": "false",
        "toolkit.telemetry.archive.enabled": "false",
        "app.shield.optoutstudies.enabled": "false",
        "browser.discovery.enabled": "false",
        "browser.newtabpage.activity-stream.feeds.telemetry": "false",
        # autoplay: 0 = izinkan audio+video, supaya antrian jalan tanpa diklik
        "media.autoplay.default": "0",
        "media.autoplay.blocking_policy": "0",
        # privasi
        "privacy.trackingprotection.enabled": "true",
        "network.cookie.cookieBehavior": "5",
        "signon.rememberSignons": "false",
        "browser.sessionstore.resume_from_crash": "false",
        "browser.tabs.warnOnClose": "false",
    }
    parsed = _parse_proxy(proxy) if proxy else None
    if parsed:
        scheme, host, port = parsed
        prefs["network.proxy.type"] = "1"
        if scheme.startswith("socks"):
            prefs["network.proxy.socks"] = f'"{host}"'
            prefs["network.proxy.socks_port"] = str(port)
            prefs["network.proxy.socks_version"] = "4" if scheme == "socks4" else "5"
            prefs["network.proxy.socks_remote_dns"] = "true"
        else:
            prefs["network.proxy.http"] = f'"{host}"'
            prefs["network.proxy.http_port"] = str(port)
            prefs["network.proxy.ssl"] = f'"{host}"'
            prefs["network.proxy.ssl_port"] = str(port)
            prefs["network.proxy.share_proxy_settings"] = "true"
    return '\n'.join(f'user_pref("{k}", {v});' for k, v in prefs.items()) + '\n'


def _place_window(pid: int, mon: dict, fullscreen: bool, timeout: float = 25.0,
                  title_hint: str = ""):
    """Geser window milik `pid` ke posisi yang dipilih.

    `title_hint` penting: satu proses browser bisa punya beberapa window terlihat
    (popup terjemahan, dialog unduhan, balon notifikasi). Tanpa penyaring, yang
    tergeser bisa saja popup-nya, dan window aslinya tetap menimpa yang lain.
    Judul halaman player memuat nama stream, jadi itu dipakai sebagai penanda;
    kalau tidak ketemu, dipilih window yang paling besar.
    """
    if sys.platform == "win32":
        _place_window_win(pid, mon, fullscreen, timeout, title_hint)
    else:
        _place_window_x11(pid, mon, fullscreen, timeout, title_hint)


_wmctrl_warned = False


def _place_window_x11(pid: int, mon: dict, fullscreen: bool, timeout: float,
                      title_hint: str = ""):
    """Cari window milik `pid` lewat `wmctrl -lp`, lalu pindahkan."""
    global _wmctrl_warned
    rect = mon["full"] if fullscreen else mon
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = subprocess.run(["wmctrl", "-lp"], capture_output=True,
                                 text=True, timeout=5).stdout
        except FileNotFoundError:
            if not _wmctrl_warned:
                _wmctrl_warned = True
                print("[launcher] wmctrl tidak ada - window Firefox tidak bisa "
                      "ditempatkan otomatis. Pasang dengan: sudo apt install wmctrl")
            return
        except Exception:
            return

        kandidat = []
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3 and parts[2] == str(pid):
                judul = parts[4] if len(parts) > 4 else ""
                # wmctrl tidak memberi ukuran; judul jadi satu-satunya penyaring
                kandidat.append((parts[0], judul, 0))
        if kandidat:
            wid = _pilih_window(kandidat, (title_hint or "").lower())
            geom = f"0,{rect['x']},{rect['y']},{rect['width']},{rect['height']}"
            subprocess.run(["wmctrl", "-i", "-r", wid, "-b",
                            "remove,maximized_vert,maximized_horz"], capture_output=True)
            subprocess.run(["wmctrl", "-i", "-r", wid, "-e", geom], capture_output=True)
            if fullscreen:
                subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,fullscreen"],
                               capture_output=True)
            return
        time.sleep(0.5)


def _place_window_win(pid: int, mon: dict, fullscreen: bool, timeout: float,
                      title_hint: str = ""):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = mon["full"] if fullscreen else mon
    deadline = time.time() + timeout
    hint = (title_hint or "").lower()

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    while time.time() < deadline:
        kandidat = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulonglong, ctypes.c_void_p)
        def _cb(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(ctypes.c_ulonglong(hwnd), ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(ctypes.c_ulonglong(hwnd)):
                return True
            n = user32.GetWindowTextLengthW(ctypes.c_ulonglong(hwnd))
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(ctypes.c_ulonglong(hwnd), buf, n + 1)
            r = RECT()
            user32.GetWindowRect(ctypes.c_ulonglong(hwnd), ctypes.byref(r))
            luas = (r.right - r.left) * (r.bottom - r.top)
            kandidat.append((hwnd, buf.value, luas))
            return True

        user32.EnumWindows(_cb, 0)
        pilihan = _pilih_window(kandidat, hint)
        if pilihan is not None:
            hwnd = ctypes.c_ulonglong(pilihan)
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE, kalau ter-minimize
            user32.SetWindowPos(hwnd, 0, rect["x"], rect["y"],
                                rect["width"], rect["height"], 0x0004)  # SWP_NOZORDER
            return
        time.sleep(0.4)


def _pilih_window(kandidat, hint: str):
    """Dari daftar (hwnd/id, judul, luas), pilih window browser yang sebenarnya.

    Prioritas: judul cocok dengan nama stream -> kalau tidak ada, yang terbesar.
    Popup seperti "Translate this page?" selalu jauh lebih kecil, jadi kalah.
    """
    if not kandidat:
        return None
    if hint:
        cocok = [k for k in kandidat if hint in (k[1] or "").lower()]
        if cocok:
            return max(cocok, key=lambda k: k[2])[0]
    return max(kandidat, key=lambda k: k[2])[0]


# --------------------------------------------------- monitor & tata letak
def resolve_monitor(wanted, monitors=None) -> dict:
    """Tentukan monitor yang benar-benar dipakai untuk sebuah stream.

    Kalau monitor yang disimpan sudah tidak terdeteksi (kabel dicabut, monitor
    mati), stream TIDAK gagal — dia jatuh ke monitor pertama yang ada, dan
    keadaan itu dilaporkan lewat `missing` supaya kelihatan di panel kontrol.
    Setelan aslinya tidak ditimpa, jadi begitu monitornya nyala lagi, stream
    kembali ke tempat semula dengan sendirinya.
    """
    mons = monitors if monitors is not None else list_monitors()
    if not mons:
        mons = [_default_monitor()]
    try:
        wanted = int(wanted or 0)
    except (TypeError, ValueError):
        wanted = 0
    missing = wanted < 0 or wanted >= len(mons)
    idx = 0 if missing else wanted
    return {"monitor": mons[idx], "index": idx, "missing": missing,
            "wanted": wanted, "total": len(mons)}


def tile_rects(rect: dict, n: int) -> list[dict]:
    """Bagi satu monitor jadi `n` petak yang tidak saling menimpa.

    1 window  -> satu layar penuh
    2 window  -> kiri | kanan
    3-4       -> kiri-atas, kanan-atas, kiri-bawah, kanan-bawah
    lebih     -> grid persegi terdekat

    Tujuannya: kalau sebuah monitor mati dan beberapa stream jatuh ke monitor
    yang sama, window-nya berjejer — bukan bertumpuk — jadi langsung kelihatan
    ada yang tidak beres.
    """
    n = max(1, int(n))
    if n == 1:
        return [dict(rect)]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w, h = rect["width"] // cols, rect["height"] // rows
    petak = []
    for i in range(n):
        r, c = divmod(i, cols)
        petak.append({
            "x": rect["x"] + c * w,
            "y": rect["y"] + r * h,
            # petak terakhir tiap baris/kolom menyerap sisa pembagian
            "width": w if c < cols - 1 else rect["width"] - c * w,
            "height": h if r < rows - 1 else rect["height"] - r * h,
        })
    return petak


def _streams_on(monitor_index: int) -> list[int]:
    """Stream yang window-nya hidup di monitor tertentu, urut sesuai id."""
    return sorted(sid for sid, info in _running.items()
                  if info["monitor"] == monitor_index and info["proc"].poll() is None)


def relayout(monitor_index: int, monitors=None):
    """Susun ulang semua window di satu monitor supaya berjejer rapi."""
    sids = _streams_on(monitor_index)
    if not sids:
        return
    mons = monitors if monitors is not None else list_monitors()
    if monitor_index >= len(mons):
        return
    petak = tile_rects(mons[monitor_index], len(sids))
    for sid, rect in zip(sids, petak):
        info = _running.get(sid)
        if not info:
            continue
        threading.Thread(
            target=_place_window,
            args=(info["proc"].pid, {**rect, "full": rect}, False, 12.0,
                  info.get("name", "")),
            daemon=True,
        ).start()


# ------------------------------------------------------------------- launch
def _privacy_flags(profile_dir: Path) -> list[str]:
    """Flag yang bikin window ini 'bersih': profil sendiri, tanpa akun, tanpa telemetri."""
    return [
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-signin-promo",
        "--disable-features=Translate,TranslateUI,OptimizationHints,MediaRouter,"
        "PrivacySandboxSettings4,InfiniteSessionRestore",
        "--disable-translate",
        "--disable-infobars",
        "--disable-background-networking",
        "--disable-breakpad",
        "--disable-domain-reliability",
        "--metrics-recording-only",
        "--no-pings",
        "--password-store=basic",
        "--autoplay-policy=no-user-gesture-required",
    ]


def _seed_chromium_prefs(profile_dir: Path):
    """Tulis Preferences awal ke profil baru.

    Flag baris perintah ternyata tidak cukup: balon "Translate this page?" tetap
    muncul karena halamannya berbahasa Indonesia. Balon itu menutup sebagian
    video dan bisa terklik anak-anak, jadi dimatikan lewat preferensi profil.
    Sekalian: tidak ada tawaran simpan password dan tidak ada izin notifikasi.
    """
    default = profile_dir / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {
        "translate": {"enabled": False},
        "translate_blocked_languages": ["id", "en"],
        "browser": {"check_default_browser": False, "has_seen_welcome_page": True},
        "credentials_enable_service": False,
        "credentials_enable_autosignin": False,
        "profile": {
            "password_manager_enabled": False,
            "default_content_setting_values": {"notifications": 2},
            "exit_type": "Normal",
            "exited_cleanly": True,
        },
        "bookmark_bar": {"show_on_all_tabs": False},
    }
    try:
        (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
    except OSError as e:
        print(f"[launcher] gagal menulis Preferences: {e}")


def _spawn(args: list[str]) -> subprocess.Popen:
    if sys.platform == "win32":
        return subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(args)


def _launch_chromium(exe: str, url: str, profile_dir: Path, mon: dict,
                     fullscreen: bool, proxy: str, title_hint: str = "") -> subprocess.Popen:
    """Chrome/Edge/Brave: posisi window diatur langsung lewat flag."""
    _seed_chromium_prefs(profile_dir)
    rect = mon["full"] if fullscreen else mon
    args = [exe, f"--app={url}"] + _privacy_flags(profile_dir) + [
        f"--window-position={rect['x']},{rect['y']}",
        f"--window-size={rect['width']},{rect['height']}",
    ]
    if fullscreen:
        args.append("--start-fullscreen")
    if proxy:
        args.append(f"--proxy-server={proxy}")
    proc = _spawn(args)
    if sys.platform != "win32":
        # Di Linux sebagian window manager mengabaikan --window-position,
        # jadi posisinya ditegaskan lagi lewat wmctrl. Aman kalau tidak perlu.
        threading.Thread(target=_place_window,
                         args=(proc.pid, mon, fullscreen, 25.0, title_hint),
                         daemon=True).start()
    return proc


def _launch_firefox(exe: str, url: str, profile_dir: Path, mon: dict,
                    fullscreen: bool, proxy: str, title_hint: str = "") -> subprocess.Popen:
    """Firefox: profil terisolasi lewat -profile, window digeser lewat WinAPI.

    Firefox tidak punya flag posisi window, jadi setelah proses jalan window-nya
    dicari lewat pid lalu dipindah ke monitor yang dipilih (lihat _place_window).
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    # user.js dibaca tiap kali Firefox start, jadi prefs selalu terpasang ulang.
    (profile_dir / "user.js").write_text(_firefox_user_js(proxy), encoding="utf-8")

    args = [exe, "-profile", str(profile_dir), "--no-remote", "--new-instance"]
    if fullscreen:
        args.append("--kiosk")
    args.append(url)
    proc = _spawn(args)

    # Tunggu window-nya muncul di thread terpisah supaya API tidak ikut menunggu.
    threading.Thread(
        target=_place_window, args=(proc.pid, mon, fullscreen, 25.0, title_hint),
        daemon=True,
    ).start()
    return proc


def launch_stream(stream: dict, base_url: str, monitors=None, fullscreen: bool = False) -> dict:
    """Buka satu window browser untuk stream ini. Return info proses."""
    info = browser_info()
    url = f"{base_url}/player/{stream['token']}"

    if info is None:
        # Tidak ada browser yang dikenali: pakai browser default, tanpa isolasi profil.
        import webbrowser

        webbrowser.open(url)
        return {"launched": True, "isolated": False, "pid": None, "url": url,
                "warning": "Chrome/Edge/Brave/Firefox tidak ditemukan - dibuka di browser "
                           "default tanpa profil terisolasi. Set BROWSER_PATH di .env "
                           "untuk isolasi penuh."}

    mons = monitors if monitors is not None else list_monitors()
    resolved = resolve_monitor(stream.get("monitor"), mons)
    mon = resolved["monitor"]

    # Berapa window yang akan berbagi monitor ini? Kalau lebih dari satu,
    # layarnya dibagi jadi petak supaya tidak ada yang tertimbun.
    idx = resolved["index"]
    total = len(_streams_on(idx)) + 1
    slot = tile_rects(mon, total)[-1]      # window baru mengambil petak terakhir
    berbagi = total > 1
    area = {**slot, "full": slot}

    profile_dir = PROFILE_ROOT / f"stream-{stream['token']}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Satu proxy untuk SEMUA window (kalau diisi) - sama seperti memasang VPN,
    # bedanya cuma browser stream yang lewat situ, browser harianmu tidak.
    proxy = (os.getenv("PROXY_SERVER") or "").strip()

    launch = _launch_firefox if info["family"] == "firefox" else _launch_chromium
    # Fullscreen tidak masuk akal kalau satu monitor dipakai beberapa window.
    proc = launch(info["path"], url, profile_dir, area,
                  fullscreen and not berbagi, proxy, stream["name"])

    _running[stream["id"]] = {"proc": proc, "profile": profile_dir,
                              "monitor": idx, "name": stream["name"]}
    if berbagi:
        # Window yang sudah ada ikut dikecilkan supaya semua kebagian petak.
        relayout(idx, mons)
    hasil = {"launched": True, "isolated": True, "pid": proc.pid, "url": url,
             "monitor": mon["label"], "browser": info["name"],
             "family": info["family"], "monitor_missing": resolved["missing"],
             "berbagi_monitor": total if berbagi else 1}
    if resolved["missing"]:
        hasil["warning"] = (
            f"Monitor {resolved['wanted'] + 1} tidak terdeteksi - "
            f"\"{stream['name']}\" pindah ke {mon['label']}"
            + (f", berbagi layar dengan {total - 1} window lain." if berbagi else ".")
        )
    return hasil


def _wipe_enabled() -> bool:
    return os.getenv("WIPE_PROFILE_ON_STOP", "1") not in ("0", "false", "False")


def reap() -> list[int]:
    """Bereskan window yang ditutup manual lewat tombol X.

    Prosesnya sudah mati tapi folder profilnya masih ada — di sini profil
    disposable-nya dihapus, sama seperti kalau distop dari GUI.
    """
    dead = []
    terdampak = set()
    for sid, info in list(_running.items()):
        if info["proc"].poll() is None:
            continue
        _running.pop(sid, None)
        terdampak.add(info["monitor"])
        if _wipe_enabled() and info["profile"].exists():
            shutil.rmtree(info["profile"], ignore_errors=True)
        dead.append(sid)
    # Window yang tersisa dilebarkan lagi mengisi ruang yang ditinggalkan.
    for idx in terdampak:
        relayout(idx)
    return dead


def is_alive(stream_id: int) -> bool:
    info = _running.get(stream_id)
    return bool(info and info["proc"].poll() is None)


def stop_stream(stream_id: int, wipe_profile=None) -> bool:
    """Tutup window stream. Profil disposable dihapus kalau WIPE_PROFILE_ON_STOP aktif."""
    info = _running.pop(stream_id, None)
    if info is None:
        return False
    proc, profile_dir = info["proc"], info["profile"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    if wipe_profile is None:
        wipe_profile = _wipe_enabled()
    if wipe_profile and profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)
    relayout(info["monitor"])     # sisanya melebar mengisi ruang kosong
    return True


def stop_all():
    for sid in list(_running):
        stop_stream(sid)


def running_ids() -> list[int]:
    for sid in list(_running):
        if not is_alive(sid):
            _running.pop(sid, None)
    return list(_running)
