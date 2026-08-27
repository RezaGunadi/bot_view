/* Player satu stream: satu window = satu playlist = satu anak.
 *
 * Setiap video diputar sebagai player/embed BARU dan URL aslinya di-"hit"
 * (dicatat ke play_log) — bukan satu iframe playlist yang jalan sendiri.
 *
 * Auto-advance:
 *   YouTube  -> IFrame API, pindah saat video benar-benar selesai (durasi asli).
 *   Lainnya  -> timer per stream (embed TikTok/FB/IG tidak punya event "ended").
 */

const TOKEN = location.pathname.split("/").pop();

const S = {
  stream: null,
  items: [],
  order: [],
  pos: -1,
  playing: false,
  yt: null,
  ytReady: false,
  timerId: null,
  countdownId: null,
  logId: null,
  startedAt: 0,
  watchdogId: null,   // video tidak pernah mulai
  stuckId: null,      // video mandek saat memuat
  sawPlaying: false,
  fails: 0,           // video gagal berturut-turut
  confirmed: false,   // sudah dilapor "benar-benar diputar"?
  sessionEndsAt: 0,   // batas waktu sesi (ms epoch); 0 = tanpa batas
  sessionTick: null,
};

const $ = (id) => document.getElementById(id);
const el = {
  who: $("who"), count: $("count"), np: $("np"), countdown: $("countdown"),
  stage: $("stage"), placeholder: $("placeholder"), phText: $("ph-text"),
  btnStart: $("btn-start"), btnPrev: $("btn-prev"), btnNext: $("btn-next"),
  btnPlay: $("btn-playpause"), session: $("session"),
};

let _ytResolve;
const _ytReady = new Promise((r) => { _ytResolve = r; });
window.onYouTubeIframeAPIReady = () => { S.ytReady = true; _ytResolve(); };

/** Tunggu YouTube IFrame API selesai dimuat (maks `ms`).
 *  Tanpa ini, video YouTube pertama selalu jatuh ke jalur timer karena
 *  script API-nya belum sempat load saat antrian dimulai. */
async function waitYtApi(ms = 6000) {
  if (S.ytReady) return true;
  await Promise.race([_ytReady, new Promise((r) => setTimeout(r, ms))]);
  return S.ytReady;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.status === 204 ? null : res.json();
}

// ----------------------------------------------------------------- antrian
function shuffle(a) {
  const r = a.slice();
  for (let i = r.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [r[i], r[j]] = [r[j], r[i]];
  }
  return r;
}

function buildOrder() {
  const idx = S.items.map((_, i) => i);
  S.order = S.stream.mode === "random" ? shuffle(idx) : idx;
}

const current = () =>
  S.pos >= 0 && S.pos < S.order.length ? S.items[S.order[S.pos]] : null;

// -------------------------------------------------------------------- hit
async function hitStart(item) {
  try {
    const r = await api(`/api/player/${TOKEN}/hit`, {
      method: "POST", body: JSON.stringify({ video_id: item.video_id }),
    });
    S.logId = r.log_id;
    S.startedAt = Date.now();
    S.confirmed = false;
  } catch (_) { S.logId = null; }
}

/** Lapor bahwa video ini sungguh mulai diputar (bukan sekadar dicoba). */
function hitConfirm() {
  if (S.confirmed || !S.logId) return;
  S.confirmed = true;
  fetch(`/api/player/${TOKEN}/hit/${S.logId}/confirm`, { method: "POST" }).catch(() => {});
}

async function hitEnd() {
  if (!S.logId) return;
  const id = S.logId;
  const secs = Math.round((Date.now() - S.startedAt) / 1000);
  S.logId = null;
  try {
    await api(`/api/player/${TOKEN}/hit/${id}/end`, {
      method: "POST", body: JSON.stringify({ seconds: secs }),
    });
  } catch (_) {}
}

// -------------------------------------------------------------- watchdog
// Dua penyebab antrian macet yang butuh orang mengklik. Keduanya masalah teknis
// (bukan jeda dari platform), jadi aman dilewati otomatis.
const NEVER_START_MS = 25000;   // tidak pernah sampai status "main"
const STUCK_MS = 45000;         // mandek di status "memuat"

/** Lewati video yang bermasalah, tapi berhenti kalau semuanya gagal.
 *  Tanpa ini, playlist yang isinya rusak semua akan berputar sangat cepat. */
function skipBroken(reason) {
  S.fails += 1;
  console.warn(`[watchdog] ${reason} - dilewati (gagal ke-${S.fails})`);
  const limit = Math.max(3, Math.min(S.items.length, 10));
  if (S.fails >= limit) {
    stopAll().then(() => {
      el.phText.textContent =
        `${S.fails} video berturut-turut tidak bisa diputar. Cek isi playlist-nya.`;
      el.btnStart.hidden = false;
      el.btnStart.textContent = "↻ Coba lagi";
    });
    return;
  }
  next();
}

function clearWatchdogs() {
  if (S.watchdogId) { clearTimeout(S.watchdogId); S.watchdogId = null; }
  if (S.stuckId) { clearTimeout(S.stuckId); S.stuckId = null; }
}

function armNeverStarted() {
  S.sawPlaying = false;
  S.watchdogId = setTimeout(() => {
    if (S.sawPlaying) return;
    skipBroken("video tidak mulai dalam 25 detik");
  }, NEVER_START_MS);
}

function armStuck() {
  if (S.stuckId) return;
  S.stuckId = setTimeout(() => {
    S.stuckId = null;
    skipBroken("video mandek saat memuat");
  }, STUCK_MS);
}

function clearStuck() {
  if (S.stuckId) { clearTimeout(S.stuckId); S.stuckId = null; }
}

// --------------------------------------------------------------- playback
function clearTimers() {
  clearWatchdogs();
  if (S.timerId) { clearTimeout(S.timerId); S.timerId = null; }
  if (S.countdownId) { clearInterval(S.countdownId); S.countdownId = null; }
  el.countdown.textContent = "";
}

function destroyPlayer() {
  if (S.yt) { try { S.yt.destroy(); } catch (_) {} S.yt = null; }
  [...el.stage.children].forEach((c) => { if (c !== el.placeholder) c.remove(); });
}

function timerFallback() {
  let remain = Math.max(5, S.stream.timer_seconds || 60);
  el.countdown.textContent = `⏱ ${remain}s`;
  S.countdownId = setInterval(() => {
    remain -= 1;
    if (remain >= 0) el.countdown.textContent = `⏱ ${remain}s`;
  }, 1000);
  S.timerId = setTimeout(next, remain * 1000);
}

async function playCurrent() {
  await hitEnd();          // tutup catatan video sebelumnya
  clearTimers();
  destroyPlayer();

  const item = current();
  if (!item) return;

  el.placeholder.hidden = true;
  S.playing = true;
  el.btnPlay.textContent = "⏸";
  el.count.textContent = `${S.pos + 1}/${S.order.length}`;
  el.np.textContent = `[${item.platform}] ${item.title || item.hit_url}`;
  document.title = `${S.stream.name} — ${item.title || item.platform}`;

  await hitStart(item);    // satu hit = satu kali nonton video ini

  if (item.platform === "youtube" && (await waitYtApi())) {
    const mount = document.createElement("div");
    el.stage.appendChild(mount);
    S.yt = new YT.Player(mount, {
      videoId: item.ext_id,
      host: "https://www.youtube-nocookie.com",
      // origin wajib diisi saat enablejsapi dipakai lewat host nocookie.
      playerVars: { autoplay: 1, rel: 0, modestbranding: 1, playsinline: 1,
                    origin: location.origin },
      events: {
        onReady: (e) => e.target.playVideo(),
        onStateChange: (e) => {
          const st = e.data;
          if (st === YT.PlayerState.PLAYING) {
            S.sawPlaying = true;
            S.fails = 0;          // ada yang berhasil main -> hitungan direset
            hitConfirm();
            clearStuck();
          } else if (st === YT.PlayerState.BUFFERING) {
            armStuck();
          } else if (st === YT.PlayerState.ENDED) {
            next();
          }
          // PAUSED sengaja dibiarkan: itu bisa jadi konfirmasi "masih menonton?"
          // dari platform, dan melanjutkannya otomatis sama saja memalsukan
          // kehadiran penonton. Keadaannya dilaporkan ke panel kontrol.
        },
        onError: () => skipBroken("video tidak bisa diputar (dihapus/private/dibatasi)"),
      },
    });
    armNeverStarted();
  } else {
    const iframe = document.createElement("iframe");
    iframe.src = item.embed_url;
    iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    iframe.referrerPolicy = "origin";
    iframe.allowFullscreen = true;
    // TikTok/FB/IG tidak memberi event "sedang main", jadi embed yang berhasil
    // dimuat dipakai sebagai bukti terdekat bahwa videonya benar tampil.
    iframe.addEventListener("load", () => { S.fails = 0; hitConfirm(); });
    el.stage.appendChild(iframe);
    timerFallback();
  }
}

function next() {
  if (!S.order.length) return;
  if (S.pos + 1 < S.order.length) {
    S.pos += 1;
  } else if (S.stream.loop_queue) {
    buildOrder();          // acak ulang tiap putaran kalau mode random
    S.pos = 0;
  } else {
    stopAll();
    return;
  }
  playCurrent();
}

function prev() {
  if (!S.order.length) return;
  if (S.pos > 0) S.pos -= 1;
  else if (S.stream.loop_queue) S.pos = S.order.length - 1;
  else return;
  playCurrent();
}

async function stopAll() {
  await hitEnd();
  clearInterval(S.sessionTick);
  clearTimers();
  S.fails = 0;
  destroyPlayer();
  S.playing = false;
  S.pos = -1;
  el.placeholder.hidden = false;
  el.phText.textContent = "Antrian selesai.";
  el.btnStart.hidden = false;
  el.btnStart.textContent = "↻ Putar lagi";
  el.np.textContent = "Selesai";
  el.btnPlay.textContent = "▶";
}

function togglePlay() {
  const item = current();
  if (!S.playing || !item) { start(); return; }
  if (S.yt && item.platform === "youtube") {
    const st = S.yt.getPlayerState();
    if (st === YT.PlayerState.PLAYING) { S.yt.pauseVideo(); el.btnPlay.textContent = "▶"; }
    else { S.yt.playVideo(); el.btnPlay.textContent = "⏸"; }
  } else if (S.timerId) {
    clearTimers();
    el.btnPlay.textContent = "▶";
  } else {
    timerFallback();
    el.btnPlay.textContent = "⏸";
  }
}

function start() {
  if (!S.items.length) return;
  startSessionLimit();
  buildOrder();
  S.pos = 0;
  playCurrent();
}

// ---- batas waktu sesi ----
function startSessionLimit() {
  clearInterval(S.sessionTick);
  const minutes = S.stream.stop_after_minutes || 0;
  if (minutes <= 0) {
    S.sessionEndsAt = 0;
    el.session.textContent = "";
    return;
  }
  S.sessionEndsAt = Date.now() + minutes * 60000;
  const tick = () => {
    const left = Math.max(0, S.sessionEndsAt - Date.now());
    const mm = Math.floor(left / 60000);
    const ss = Math.floor((left % 60000) / 1000);
    el.session.textContent = `sesi ${mm}:${String(ss).padStart(2, "0")}`;
    if (left <= 0) {
      clearInterval(S.sessionTick);
      endSession();
    }
  };
  tick();
  S.sessionTick = setInterval(tick, 1000);
}

async function endSession() {
  await stopAll();
  el.phText.textContent = "Waktu sesi habis.";
  el.session.textContent = "";
  el.btnStart.textContent = "▶ Mulai sesi baru";
  el.btnStart.hidden = false;
}

// ------------------------------------------------------------------- init
el.btnNext.onclick = next;
el.btnPrev.onclick = prev;
el.btnPlay.onclick = togglePlay;
el.btnStart.onclick = start;

document.addEventListener("keydown", (e) => {
  if (e.key === " ") { e.preventDefault(); togglePlay(); }
  if (e.key === "ArrowRight") next();
  if (e.key === "ArrowLeft") prev();
  if (e.key === "f") document.documentElement.requestFullscreen?.();
});

window.addEventListener("beforeunload", () => {
  if (!S.logId) return;
  // sendBeacon: catatan tetap tertutup walau window langsung ditutup
  const secs = Math.round((Date.now() - S.startedAt) / 1000);
  navigator.sendBeacon(
    `/api/player/${TOKEN}/hit/${S.logId}/end`,
    new Blob([JSON.stringify({ seconds: secs })], { type: "application/json" }),
  );
});

(async function init() {
  try {
    const cfg = await api(`/api/player/${TOKEN}`);
    S.stream = cfg.stream;
    S.items = cfg.items;
    el.who.textContent = S.stream.name;
    document.title = S.stream.name;
    el.count.textContent = `0/${S.items.length}`;

    if (!S.items.length) {
      el.phText.textContent = "Playlist ini masih kosong.";
      return;
    }
    el.phText.textContent =
      `${S.stream.name} · ${S.items.length} video dari "${S.stream.playlist_name}"`;
    el.btnStart.hidden = false;

    // Coba autoplay langsung; kalau browser menolak, tombol Mulai tetap tersedia.
    start();
  } catch (e) {
    el.phText.textContent = "Gagal memuat stream: " + e.message;
  }
})();
