/* Control panel: playlist, isi playlist, dan stream (multi-window). */

const state = {
  playlists: [], items: [], streams: [], monitors: [], schedules: [],
  selected: null,     // playlist yang sedang dibuka
  filter: "",
};

const $ = (id) => document.getElementById(id);
const el = {
  stats: $("stats"), env: $("env-info"), toast: $("toast"),
  playlistList: $("playlist-list"), itemList: $("item-list"),
  streamList: $("stream-list"), logList: $("log-list"),
  scheduleList: $("schedule-list"), fixMonitors: $("btn-fix-monitors"),
  itemsTitle: $("items-title"), itemsCount: $("items-count"),
  addForm: $("add-form"), url: $("url-input"), title: $("title-input"),
  bulkForm: $("bulk-form"), bulk: $("bulk-input"), search: $("item-search"),
  excelFile: $("excel-file"), importResult: $("import-result"),
  fullscreen: $("opt-fullscreen"),
  modal: $("modal"), mTitle: $("modal-title"), mBody: $("modal-body"),
  mInput: $("modal-input"), mOk: $("modal-ok"), mCancel: $("modal-cancel"),
  mForm: $("modal-form"),
};

// ═══════════════════════════════════════════════════ util
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b.detail) msg = b.detail; } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

let toastTimer = null;
function toast(msg, kind = "") {
  el.toast.textContent = msg;
  el.toast.className = "toast " + kind;
  el.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.toast.hidden = true), 5000);
}

function tag(name, cls, text) {
  const n = document.createElement(name);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function iconBtn(label, title, onClick, cls = "") {
  const b = tag("button", "icon-btn " + cls, label);
  b.title = title;
  b.onclick = (e) => { e.stopPropagation(); onClick(); };
  return b;
}

/** Pengganti prompt()/confirm(). Return string (input) / true / null kalau dibatalkan. */
function ask({ title, body = "", value = null, ok = "OK", danger = false }) {
  return new Promise((resolve) => {
    el.mTitle.textContent = title;
    el.mBody.textContent = body;
    el.mForm.hidden = true;
    el.mForm.innerHTML = "";
    el.mInput.hidden = value === null;
    el.mInput.value = value ?? "";
    el.mOk.textContent = ok;
    el.mOk.className = danger ? "danger" : "primary";
    el.modal.hidden = false;
    if (value !== null) setTimeout(() => { el.mInput.focus(); el.mInput.select(); }, 30);

    const done = (result) => {
      el.modal.hidden = true;
      el.mOk.onclick = el.mCancel.onclick = null;
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const submit = () => done(value === null ? true : el.mInput.value.trim());
    const onKey = (e) => {
      if (e.key === "Escape") done(null);
      if (e.key === "Enter" && value !== null) { e.preventDefault(); submit(); }
    };
    el.mOk.onclick = submit;
    el.mCancel.onclick = () => done(null);
    document.addEventListener("keydown", onKey);
  });
}

el.modal.addEventListener("click", (e) => { if (e.target === el.modal) el.mCancel.click(); });

// ═══════════════════════════════════════════════════ muat data
async function refreshAll() {
  const [playlists, streams, mon, stats, schedules] = await Promise.all([
    api("/api/playlists"), api("/api/streams"), api("/api/monitors"), api("/api/stats"),
    api("/api/schedules"),
  ]);
  state.playlists = playlists;
  state.streams = streams;
  state.monitors = mon.monitors;
  state.schedules = schedules;

  el.stats.innerHTML = "";
  [["video", stats.videos], ["playlist", stats.playlists],
   ["stream", stats.streams], ["tayangan", stats.plays]].forEach(([label, n]) => {
    const c = tag("span", "chip");
    c.append(tag("b", "", String(n)), document.createTextNode(" " + label));
    el.stats.appendChild(c);
  });

  // Window yang tidak bisa ditempatkan akan saling menimpa. Itu kelihatan di
  // layar tapi sebabnya tidak, jadi ditulis di tempat yang pasti terbaca.
  if (mon.placement && !mon.placement.ok) {
    const w = tag("span", "chip warn", "⚠ " + mon.placement.reason);
    w.title = mon.placement.reason;
    el.stats.appendChild(w);
  }

  const b = mon.browser_name || "browser default";
  el.env.textContent = `${b} · ${state.monitors.length} monitor`;
  el.env.title = mon.browser || "Tidak ada Chrome/Edge/Brave/Firefox terdeteksi";

  if (state.selected == null && playlists.length) state.selected = playlists[0].id;
  if (state.selected != null && !playlists.some((p) => p.id === state.selected)) {
    state.selected = playlists.length ? playlists[0].id : null;
  }

  renderPlaylists();
  renderStreams();
  renderSchedules();
  await loadItems();
  await loadLog();
}

async function loadItems() {
  state.items = state.selected == null
    ? [] : await api(`/api/playlists/${state.selected}/items`);
  renderItems();
}

async function loadLog() {
  const plays = await api("/api/plays?limit=40");
  el.logList.innerHTML = "";
  if (!plays.length) {
    el.logList.appendChild(tag("li", "empty", "Belum ada video yang diputar."));
    return;
  }
  plays.forEach((p) => {
    const li = tag("li");
    const dur = p.seconds != null ? `${p.seconds}s` : "…";
    li.append(
      tag("span", "when", (p.started_at || "").slice(11, 16)),
      tag("span", "what", `${p.stream_name || "—"} · ${p.title || p.url}`),
      tag("span", "when", dur),
    );
    li.title = p.url;
    el.logList.appendChild(li);
  });
}

// ═══════════════════════════════════════════════════ playlist
function renderPlaylists() {
  el.playlistList.innerHTML = "";
  if (!state.playlists.length) {
    el.playlistList.appendChild(tag("li", "empty", "Belum ada playlist."));
    return;
  }
  state.playlists.forEach((p) => {
    const li = tag("li", "card pl-row" + (p.id === state.selected ? " selected" : ""));
    const box = tag("div", "grow");
    box.append(tag("span", "name", p.name));
    li.append(box, tag("span", "count", String(p.item_count)));
    li.onclick = () => {
      state.selected = p.id;
      state.filter = "";
      el.search.value = "";
      renderPlaylists();
      loadItems();
    };
    li.ondblclick = () => renamePlaylist(p);
    li.title = "Klik dua kali untuk ganti nama";
    el.playlistList.appendChild(li);
  });
}

$("btn-new-playlist").onclick = async () => {
  const name = await ask({
    title: "Playlist baru",
    body: "Misalnya nama kelompok atau tema: “Kelas A”, “Lagu tidur”.",
    value: `Playlist ${state.playlists.length + 1}`,
  });
  if (!name) return;
  const created = await api("/api/playlists", { method: "POST", body: JSON.stringify({ name }) });
  state.selected = created.id;
  await refreshAll();
  toast(`Playlist "${created.name}" dibuat.`, "ok");
};

async function renamePlaylist(p) {
  const name = await ask({ title: "Ganti nama playlist", value: p.name });
  if (!name || name === p.name) return;
  await api(`/api/playlists/${p.id}`, { method: "PUT", body: JSON.stringify({ name }) });
  await refreshAll();
}

$("btn-check-playlist").onclick = async () => {
  if (state.selected == null) return toast("Pilih playlist dulu.", "err");
  const btn = $("btn-check-playlist");
  btn.disabled = true;
  btn.textContent = "Memeriksa…";
  try {
    const r = await api(`/api/playlists/${state.selected}/check`, { method: "POST" });
    state.items = r.items;
    renderItems();
    toast(r.broken.length
      ? `${r.checked} video diperiksa — ${r.broken.length} bermasalah (ditandai merah).`
      : `${r.checked} video diperiksa, semua sehat.`,
      r.broken.length ? "err" : "ok");
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "✓ Periksa";
  }
};

$("btn-copy-playlist").onclick = async () => {
  if (state.selected == null) return toast("Pilih playlist dulu.", "err");
  const src = state.playlists.find((p) => p.id === state.selected);
  const name = await ask({
    title: "Salin playlist",
    body: `${src.item_count} video akan ikut tersalin. Video-nya dipakai bersama, jadi menghapus dari salinan tidak mengubah yang asli.`,
    value: `${src.name} - salinan`,
  });
  if (name === null) return;
  const copy = await api(`/api/playlists/${state.selected}/copy`, {
    method: "POST", body: JSON.stringify({ name: name || null }),
  });
  state.selected = copy.id;
  await refreshAll();
  toast(`Disalin jadi "${copy.name}".`, "ok");
};

$("btn-del-playlist").onclick = async () => {
  if (state.selected == null) return;
  const src = state.playlists.find((p) => p.id === state.selected);
  const yes = await ask({
    title: `Hapus "${src.name}"?`,
    body: "Playlist-nya hilang, tapi video-videonya tetap ada di library dan playlist lain.",
    ok: "Hapus", danger: true,
  });
  if (!yes) return;
  await api(`/api/playlists/${state.selected}`, { method: "DELETE" });
  state.selected = null;
  await refreshAll();
  toast("Playlist dihapus.", "ok");
};

// ═══════════════════════════════════════════════════ isi playlist
function visibleItems() {
  const q = state.filter.toLowerCase();
  if (!q) return state.items;
  return state.items.filter(
    (i) => (i.title || "").toLowerCase().includes(q) || i.url.toLowerCase().includes(q)
  );
}

function renderItems() {
  const pl = state.playlists.find((p) => p.id === state.selected);
  el.itemsTitle.textContent = pl ? pl.name : "Isi playlist";
  el.itemsCount.textContent = `${state.items.length} video`;
  el.itemList.innerHTML = "";

  if (state.selected == null) {
    el.itemList.appendChild(tag("li", "empty", "Buat atau pilih playlist dulu."));
    return;
  }
  const list = visibleItems();
  if (!list.length) {
    el.itemList.appendChild(tag("li", "empty",
      state.items.length ? "Tidak ada yang cocok dengan pencarian."
                         : "Playlist kosong — tempel link di atas."));
    return;
  }

  list.forEach((it) => {
    const realIdx = state.items.indexOf(it);
    const li = tag("li", "card item");
    li.draggable = !state.filter;   // drag hanya masuk akal saat tidak difilter
    li.dataset.itemId = it.item_id;

    const name = tag("span", "name", it.title || it.hit_url);
    name.title = "Klik dua kali untuk ubah judul";
    name.ondblclick = () => editTitle(it, name);

    const box = tag("div", "grow");
    box.append(name);
    // URL cuma ditampilkan sebagai baris kedua kalau judulnya sudah diisi,
    // supaya tidak muncul dua kali untuk video yang belum diberi judul.
    if (it.title) box.append(tag("span", "sub", it.hit_url));

    const BROKEN = ["dihapus", "private", "tidak bisa diputar"];
    if (BROKEN.includes(it.status)) {
      li.classList.add("broken");
      const mark = tag("span", "state warn", it.status);
      mark.title = "Ketahuan saat Periksa. Video ini akan dilewati otomatis saat tayang.";
      box.append(mark);
    }

    li.append(
      tag("span", "handle", state.filter ? "" : "⠿"),
      tag("span", "idx", String(realIdx + 1)),
      tag("span", "badge " + it.platform, it.platform.slice(0, 2)),
      box,
      tag("span", "plays", `${it.play_count}×`),
      iconBtn("✕", "Hapus dari playlist ini", () => removeItem(it), "danger"),
    );
    attachDrag(li);
    el.itemList.appendChild(li);
  });
}

async function editTitle(it, node) {
  const title = await ask({ title: "Judul video", value: it.title || "" });
  if (title === null) return;
  await api(`/api/videos/${it.video_id}`, {
    method: "PUT", body: JSON.stringify({ title: title || null }),
  });
  await loadItems();
}

// ---- drag & drop untuk mengurutkan ----
let dragId = null;
function attachDrag(li) {
  li.addEventListener("dragstart", () => {
    dragId = Number(li.dataset.itemId);
    li.classList.add("dragging");
  });
  li.addEventListener("dragend", () => {
    li.classList.remove("dragging");
    document.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
  });
  li.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (Number(li.dataset.itemId) !== dragId) li.classList.add("drop-target");
  });
  li.addEventListener("dragleave", () => li.classList.remove("drop-target"));
  li.addEventListener("drop", async (e) => {
    e.preventDefault();
    li.classList.remove("drop-target");
    const targetId = Number(li.dataset.itemId);
    if (!dragId || dragId === targetId) return;
    const order = state.items.map((i) => i.item_id);
    const from = order.indexOf(dragId);
    const to = order.indexOf(targetId);
    order.splice(to, 0, ...order.splice(from, 1));
    state.items = await api(`/api/playlists/${state.selected}/items/reorder`, {
      method: "POST", body: JSON.stringify({ order }),
    });
    renderItems();
  });
}

async function removeItem(it) {
  await api(`/api/playlists/${state.selected}/items/${it.item_id}`, { method: "DELETE" });
  await loadItems();
  state.playlists = await api("/api/playlists");
  renderPlaylists();
  renderStreams();
}

el.search.addEventListener("input", () => {
  state.filter = el.search.value.trim();
  renderItems();
});

// ---- tab satu link / banyak sekaligus ----
function showTab(name) {
  document.querySelectorAll(".tab").forEach((x) =>
    x.classList.toggle("active", x.dataset.tab === name));
  document.querySelectorAll(".add-pane").forEach((p) => {
    p.hidden = p.dataset.pane !== name;
  });
}

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => showTab(t.dataset.tab);
});

// Buka tab tertentu langsung lewat alamat, mis. .../#excel
if (location.hash === "#excel") showTab("excel");

el.addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.selected == null) return toast("Pilih playlist dulu.", "err");
  const url = el.url.value.trim();
  if (!url) return;
  try {
    await api(`/api/playlists/${state.selected}/items`, {
      method: "POST",
      body: JSON.stringify({ url, title: el.title.value.trim() || null }),
    });
    el.url.value = ""; el.title.value = "";
    await loadItems();
    await refreshCounts();
  } catch (err) { toast(err.message, "err"); }
});

el.bulkForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.selected == null) return toast("Pilih playlist dulu.", "err");
  const urls = el.bulk.value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return;

  let ok = 0;
  const failed = [];
  for (const url of urls) {
    try {
      await api(`/api/playlists/${state.selected}/items`, {
        method: "POST", body: JSON.stringify({ url }),
      });
      ok++;
    } catch (_) { failed.push(url); }
  }
  el.bulk.value = failed.join("\n");   // sisakan yang gagal supaya bisa diperbaiki
  await loadItems();
  await refreshCounts();
  toast(failed.length
    ? `${ok} masuk, ${failed.length} link tidak dikenali (ditinggal di kotak).`
    : `${ok} video ditambahkan.`, failed.length ? "err" : "ok");
});

async function refreshCounts() {
  state.playlists = await api("/api/playlists");
  renderPlaylists();
  renderStreams();
}

// ═══════════════════════════════════════════════════ stream
function selectField(label, options, value, onChange) {
  const f = tag("div", "field");
  f.append(tag("label", "", label));
  const sel = document.createElement("select");
  options.forEach(([val, text]) => {
    const o = tag("option", "", text);
    o.value = val;
    sel.appendChild(o);
  });
  sel.value = String(value);
  sel.onchange = () => onChange(sel.value);
  f.appendChild(sel);
  return f;
}

function numberField(label, value, onChange, opts = {}) {
  const f = tag("div", "field");
  f.append(tag("label", "", label));
  const inp = document.createElement("input");
  inp.type = "number";
  inp.value = value;
  inp.min = opts.min ?? 0;
  inp.max = opts.max ?? 3600;
  if (opts.title) inp.title = opts.title;
  inp.onchange = () => onChange(Number(inp.value));
  f.appendChild(inp);
  return f;
}

async function patchStream(s, patch) {
  await api(`/api/streams/${s.id}`, { method: "PUT", body: JSON.stringify(patch) });
  state.streams = await api("/api/streams");
  renderStreams();
}

/** Keadaan player yang dilaporkan window-nya sendiri (tiap 20 detik).
 *  Dipakai untuk melihat ruangan mana yang playernya terjeda atau diam. */
function streamStatus(s) {
  if (!s.running) {
    if (s.status === "crashed") {
      const n = tag("span", "state warn", "mati sendiri");
      n.title = s.auto_restart
        ? "Akan dinyalakan lagi otomatis dalam beberapa detik."
        : "Auto-restart mati, jadi dibiarkan berhenti.";
      return n;
    }
    return tag("span", "sub", "");
  }
  if (!s.last_seen) return tag("span", "state", "menunggu kabar…");

  const ageSec = Math.round((Date.now() - new Date(s.last_seen).getTime()) / 1000);
  if (ageSec > 90) {
    const n = tag("span", "state warn", `tidak merespons ${Math.round(ageSec / 60)} mnt`);
    n.title = "Window-nya mungkin ditutup atau halamannya bermasalah.";
    return n;
  }
  if (s.last_state === "terjeda") {
    const n = tag("span", "state warn", "terjeda");
    n.title = "Perlu diklik di ruangan itu untuk lanjut.";
    return n;
  }
  return tag("span", "state ok", s.last_state || "main");
}

function renderStreams() {
  // Tombol "pindahkan" hanya muncul kalau memang ada monitor yang hilang.
  const bermasalah = state.streams.filter((s) => s.monitor_missing);
  el.fixMonitors.hidden = bermasalah.length === 0;
  el.fixMonitors.textContent = `⚠ Pindahkan ${bermasalah.length}`;

  el.streamList.innerHTML = "";
  if (!state.streams.length) {
    el.streamList.appendChild(tag("li", "empty",
      "Belum ada stream. Buat satu untuk tiap kelompok/monitor."));
    return;
  }

  const playlistOpts = state.playlists.map((p) => [p.id, `${p.name} (${p.item_count})`]);
  const monitorOpts = state.monitors.map((m) => [m.index, m.label]);

  /** Kalau monitor yang tersimpan sudah tidak ada, dia tetap dimunculkan sebagai
   *  pilihan bertanda - supaya dropdown tidak diam-diam menampilkan monitor lain. */
  const monitorOptsFor = (s) => (s.monitor_missing
    ? [...monitorOpts, [s.monitor, `Monitor ${s.monitor + 1} (tidak terdeteksi)`]]
    : monitorOpts);

  state.streams.forEach((s) => {
    const li = tag("li", "card stream" + (s.running ? " running" : ""));

    // -- baris atas: status, nama (bisa langsung diketik), tombol putar/stop
    const top = tag("div", "stream-top");
    const nameInput = document.createElement("input");
    nameInput.className = "stream-name-input grow";
    nameInput.value = s.name;
    nameInput.onchange = () => patchStream(s, { name: nameInput.value.trim() || s.name });

    const playBtn = tag("button", "btn-play " + (s.running ? "" : "primary"),
                        s.running ? "⏹ Stop" : "▶ Putar");
    playBtn.onclick = () => (s.running ? stopStream(s) : startStream(s));

    top.append(tag("span", "dot" + (s.running ? " on" : "")), nameInput, playBtn,
               iconBtn("🗑", "Hapus stream", () => deleteStream(s), "danger"));

    // -- grid pengaturan
    const grid = tag("div", "stream-grid");
    grid.append(
      selectField("Playlist", playlistOpts, s.playlist_id ?? "",
                  (v) => patchStream(s, { playlist_id: Number(v) })),
      selectField("Monitor", monitorOptsFor(s), s.monitor,
                  (v) => patchStream(s, { monitor: Number(v) })),
      selectField("Urutan", [["sequential", "Urut"], ["random", "Acak"]], s.mode,
                  (v) => patchStream(s, { mode: v })),
      numberField("Timer non-YT (detik)", s.timer_seconds,
                  (v) => patchStream(s, { timer_seconds: v }),
                  { min: 5, max: 3600,
                    title: "Berapa lama video TikTok/FB/IG ditampilkan sebelum lanjut" }),
      numberField("Batas sesi (menit)", s.stop_after_minutes,
                  (v) => patchStream(s, { stop_after_minutes: v }),
                  { min: 0, max: 1440,
                    title: "Window berhenti sendiri setelah sekian menit. 0 = tanpa batas." }),
    );
    grid.lastChild.classList.add("wide");

    // -- baris bawah: loop + info
    const foot = tag("div", "stream-foot");
    const loopWrap = tag("label", "switch");
    const loopBox = document.createElement("input");
    loopBox.type = "checkbox";
    loopBox.checked = !!s.loop_queue;
    loopBox.onchange = () => patchStream(s, { loop_queue: loopBox.checked });
    loopWrap.append(loopBox, tag("span", "", "Ulang antrian"));

    const restartWrap = tag("label", "switch");
    const restartBox = document.createElement("input");
    restartBox.type = "checkbox";
    restartBox.checked = !!s.auto_restart;
    restartBox.onchange = () => patchStream(s, { auto_restart: restartBox.checked });
    restartWrap.append(restartBox, tag("span", "", "Nyalakan lagi kalau mati sendiri"));
    restartWrap.title = "Kalau window-nya hilang tanpa distop dari panel, dibuka lagi "
                      + "otomatis (maks 5x per jam).";

    foot.append(loopWrap, restartWrap, streamStatus(s));

    // Peringatan monitor hilang — stream tetap jalan, hanya pindah sementara.
    let warnRow = null;
    if (s.monitor_missing) {
      warnRow = tag("div", "monitor-warn");
      warnRow.append(
        tag("span", "mw-icon", "⚠"),
        tag("span", "mw-text",
            `Monitor ${s.monitor + 1} tidak terdeteksi — dipakai ${s.monitor_label}`),
      );
      warnRow.title = "Setelanmu tidak diubah. Begitu monitornya nyala lagi, "
                    + "stream ini kembali ke sana sendiri.";
    }

    // Baris "sedang memutar" — dari kabar yang dikirim window-nya sendiri.
    li.append(top);
    if (warnRow) li.append(warnRow);
    if (s.running && s.last_title) {
      const np = tag("div", "now-playing");
      np.append(tag("span", "np-icon", "♪"), tag("span", "np-text", s.last_title));
      np.title = s.last_title;
      li.append(np);
    }
    li.append(grid, foot);
    el.streamList.appendChild(li);
  });
}

$("btn-new-stream").onclick = async () => {
  if (!state.playlists.length) return toast("Buat playlist dulu.", "err");
  const nextMonitor = Math.min(state.streams.length, state.monitors.length - 1);
  const v = await askForm({
    title: "Stream baru",
    body: "Satu stream = satu window browser di satu monitor.",
    fields: [
      { key: "name", label: "Nama", value: `Ruang ${state.streams.length + 1}`,
        placeholder: "mis. Ruang Balita" },
      { key: "playlist_id", label: "Playlist", type: "select",
        value: state.selected ?? state.playlists[0].id,
        options: state.playlists.map((p) => [p.id, `${p.name} (${p.item_count})`]) },
      { key: "monitor", label: "Monitor", type: "select", value: nextMonitor,
        options: state.monitors.map((m) => [m.index, m.label]) },
    ],
  });
  if (!v) return;
  if (!v.name) return toast("Nama stream belum diisi.", "err");
  await api("/api/streams", {
    method: "POST",
    body: JSON.stringify({
      name: v.name,
      playlist_id: Number(v.playlist_id),
      monitor: Number(v.monitor),
      mode: "sequential", timer_seconds: 60, loop_queue: true,
      stop_after_minutes: 0, auto_restart: true,
    }),
  });
  await refreshAll();
  toast(`Stream "${v.name}" dibuat. Klik Putar untuk membuka window-nya.`, "ok");
};

async function startStream(s) {
  try {
    const fs = el.fullscreen.checked ? "?fullscreen=true" : "";
    const info = await api(`/api/streams/${s.id}/start${fs}`, { method: "POST" });
    toast(info.warning || `"${s.name}" dibuka di ${info.monitor} (${info.browser}).`,
          info.warning ? "err" : "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
}

async function stopStream(s) {
  await api(`/api/streams/${s.id}/stop`, { method: "POST" });
  await refreshAll();
}

async function deleteStream(s) {
  const yes = await ask({ title: `Hapus stream "${s.name}"?`, ok: "Hapus", danger: true });
  if (!yes) return;
  await api(`/api/streams/${s.id}`, { method: "DELETE" });
  await refreshAll();
}

$("btn-start-all").onclick = async () => {
  const fs = el.fullscreen.checked ? "?fullscreen=true" : "";
  const r = await api(`/api/streams/start-all${fs}`, { method: "POST" });
  const opened = r.results.filter((x) => x.launched).length;
  const skipped = r.results.filter((x) => x.skipped);
  toast(`${opened} window dibuka.` + (skipped.length
    ? ` Dilewati: ${skipped.map((x) => `${x.name} (${x.skipped})`).join(", ")}` : ""),
    opened ? "ok" : "err");
  await refreshAll();
};

$("btn-fix-monitors").onclick = async () => {
  const bermasalah = state.streams.filter((s) => s.monitor_missing);
  const yes = await ask({
    title: "Pindahkan ke monitor yang ada?",
    body: [
      `${bermasalah.length} stream disetel ke monitor yang tidak terdeteksi:`,
      ...bermasalah.map((s) => `• ${s.name} → Monitor ${s.monitor + 1}`),
      "",
      "Setelannya akan diubah permanen. Kalau monitornya cuma mati sementara,",
      "tidak perlu dipindah — stream sudah otomatis tampil di monitor yang ada.",
    ].join('\n'),
    ok: "Pindahkan",
  });
  if (!yes) return;
  const r = await api("/api/streams/reassign-monitors", { method: "POST" });
  await refreshAll();
  toast(`${r.dipindah.length} stream dipindahkan ke monitor yang tersedia.`, "ok");
};

$("btn-rescan").onclick = async () => {
  const sebelum = state.monitors.length;
  const mon = await api("/api/monitors");
  state.monitors = mon.monitors;
  await refreshAll();
  const n = state.monitors.length;
  toast(n === sebelum
    ? `Terdeteksi ${n} monitor (tidak berubah).`
    : `Monitor berubah: ${sebelum} → ${n}.`, "ok");
};

$("btn-stop-all").onclick = async () => {
  await api("/api/streams/stop-all", { method: "POST" });
  await refreshAll();
};

$("btn-refresh-log").onclick = loadLog;

// Status window (jalan/tutup) diperbarui berkala tanpa mengganggu isian yang sedang diedit.
setInterval(async () => {
  if (document.activeElement && document.activeElement.closest(".stream")) return;
  if (!el.modal.hidden) return;
  try {
    const [streams, mon] = await Promise.all([api("/api/streams"), api("/api/monitors")]);
    const berubah = mon.monitors.length !== state.monitors.length;
    state.streams = streams;
    state.monitors = mon.monitors;
    renderStreams();
    if (berubah) {
      el.env.textContent =
        `${mon.browser_name || "browser default"} · ${state.monitors.length} monitor`;
      toast(`Jumlah monitor berubah jadi ${state.monitors.length}.`, "");
    }
  } catch (_) {}
}, 5000);

refreshAll().catch((e) => toast(e.message, "err"));

// ═══════════════════════════════════════════════════ jadwal otomatis
const DAY_NAMES = { 1: "Sen", 2: "Sel", 3: "Rab", 4: "Kam", 5: "Jum", 6: "Sab", 7: "Min" };

function daysLabel(days) {
  const list = (days || "").split(",").map((d) => d.trim()).filter(Boolean);
  if (list.length === 7) return "tiap hari";
  if (list.join(",") === "1,2,3,4,5") return "Sen–Jum";
  return list.map((d) => DAY_NAMES[d] || d).join(" ");
}

function renderSchedules() {
  el.scheduleList.innerHTML = "";
  if (!state.schedules.length) {
    el.scheduleList.appendChild(tag("li", "empty",
      "Belum ada jadwal. Stream dinyalakan manual."));
    return;
  }
  state.schedules.forEach((sc) => {
    const li = tag("li", "card sched" + (sc.enabled ? "" : " off"));
    const box = tag("div", "grow");
    box.append(
      tag("span", "name", `${sc.start_time} – ${sc.stop_time}  ${sc.name}`),
      tag("span", "sub", `${daysLabel(sc.days)} · ${sc.stream_name || "semua stream"}`),
    );
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = !!sc.enabled;
    toggle.title = "Aktif / nonaktif";
    toggle.onchange = async () => {
      await api(`/api/schedules/${sc.id}`, {
        method: "PUT", body: JSON.stringify({ enabled: toggle.checked }),
      });
      await refreshAll();
    };
    box.style.cursor = "pointer";
    box.title = "Klik untuk mengubah jadwal ini";
    box.onclick = () => editSchedule(sc);
    li.append(toggle, box, iconBtn("🗑", "Hapus jadwal", () => deleteSchedule(sc), "danger"));
    el.scheduleList.appendChild(li);
  });
}

async function deleteSchedule(sc) {
  const yes = await ask({ title: `Hapus jadwal "${sc.name}"?`, ok: "Hapus", danger: true });
  if (!yes) return;
  await api(`/api/schedules/${sc.id}`, { method: "DELETE" });
  await refreshAll();
}

function scheduleFields(sc = {}) {
  return [
    { key: "name", label: "Nama jadwal", value: sc.name ?? "Jam sekolah",
      placeholder: "mis. Jam sekolah" },
    { key: "start_time", label: "Mulai", type: "time", value: sc.start_time ?? "08:00",
      half: true },
    { key: "stop_time", label: "Selesai", type: "time", value: sc.stop_time ?? "16:00",
      half: true },
    { key: "days", label: "Hari", type: "days", value: sc.days ?? "1,2,3,4,5" },
    { key: "stream_id", label: "Berlaku untuk", type: "select",
      value: sc.stream_id ?? "0",
      options: [["0", "Semua stream"], ...state.streams.map((s) => [s.id, s.name])] },
  ];
}

function validSchedule(v) {
  if (!v.name) return "Nama jadwal belum diisi.";
  if (!/^\d{2}:\d{2}$/.test(v.start_time) || !/^\d{2}:\d{2}$/.test(v.stop_time)) {
    return "Jam harus dalam format HH:MM.";
  }
  if (!v.days) return "Pilih minimal satu hari.";
  if (v.start_time === v.stop_time) return "Jam mulai dan selesai tidak boleh sama.";
  return null;
}

$("btn-new-schedule").onclick = async () => {
  const v = await askForm({
    title: "Jadwal baru",
    body: "Stream dinyalakan pada jam mulai dan dimatikan pada jam selesai. "
        + "Kalau kamu matikan window manual di tengah jadwal, dia tidak dinyalakan "
        + "ulang sampai jadwal berikutnya.",
    fields: scheduleFields(),
  });
  if (!v) return;
  const salah = validSchedule(v);
  if (salah) return toast(salah, "err");
  try {
    await api("/api/schedules", {
      method: "POST",
      body: JSON.stringify({ ...v, stream_id: Number(v.stream_id) || null }),
    });
    await refreshAll();
    toast(`Jadwal "${v.name}" ${v.start_time}–${v.stop_time} disimpan.`, "ok");
  } catch (e) { toast(e.message, "err"); }
};

async function editSchedule(sc) {
  const v = await askForm({
    title: "Ubah jadwal",
    fields: scheduleFields(sc),
  });
  if (!v) return;
  const salah = validSchedule(v);
  if (salah) return toast(salah, "err");
  await api(`/api/schedules/${sc.id}`, {
    method: "PUT",
    body: JSON.stringify({ ...v, stream_id: Number(v.stream_id) || 0 }),
  });
  await refreshAll();
  toast("Jadwal diperbarui.", "ok");
}

// ═══════════════════════════════════════════════════ impor dari Excel
$("btn-pick-file").onclick = () => el.excelFile.click();

el.excelFile.addEventListener("change", async () => {
  const file = el.excelFile.files[0];
  if (!file) return;
  const btn = $("btn-pick-file");
  btn.disabled = true;
  btn.textContent = "Mengimpor…";
  el.importResult.hidden = true;

  try {
    const body = new FormData();
    body.append("file", file);
    // playlist_id dipakai untuk baris yang kolom playlist-nya kosong
    const q = state.selected != null ? `?playlist_id=${state.selected}` : "";
    const res = await fetch(`/api/import${q}`, { method: "POST", body });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const b = await res.json(); if (b.detail) msg = b.detail; } catch (_) {}
      throw new Error(msg);
    }
    const r = await res.json();

    const lines = [`${r.ditambahkan} dari ${r.total_baris} baris masuk.`];
    if (r.playlist_baru.length) {
      lines.push(`Playlist baru dibuat: ${r.playlist_baru.join(", ")}.`);
    }
    if (r.gagal.length) {
      lines.push(`Gagal ${r.gagal.length} baris:`);
      r.gagal.slice(0, 8).forEach((g) => lines.push(`  baris ${g.baris}: ${g.sebab} — ${g.url}`));
      if (r.gagal.length > 8) lines.push(`  …dan ${r.gagal.length - 8} lagi.`);
    }
    el.importResult.textContent = lines.join("\n");
    el.importResult.hidden = false;

    await refreshAll();
    toast(r.gagal.length
      ? `${r.ditambahkan} video masuk, ${r.gagal.length} baris bermasalah.`
      : `${r.ditambahkan} video masuk dari Excel.`,
      r.gagal.length ? "err" : "ok");
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "⬆ Upload file terisi";
    el.excelFile.value = "";   // supaya file yang sama bisa diupload ulang
  }
});

// ═══════════════════════════════════════════════════ modal berisi form
const HARI = [[1, "Sen"], [2, "Sel"], [3, "Rab"], [4, "Kam"], [5, "Jum"],
              [6, "Sab"], [7, "Min"]];

/** Bikin satu baris field. Return {node, read} — `read` mengambil nilainya. */
function buildField(f) {
  const wrap = tag("div", "field");
  if (f.label) wrap.append(tag("label", "", f.label));

  if (f.type === "days") {
    const box = tag("div", "days");
    const aktif = new Set((f.value || "").split(",").map((d) => d.trim()).filter(Boolean));
    HARI.forEach(([num, nama]) => {
      const chip = tag("div", "day-chip" + (aktif.has(String(num)) ? " on" : ""), nama);
      chip.onclick = () => {
        const on = chip.classList.toggle("on");
        if (on) aktif.add(String(num)); else aktif.delete(String(num));
      };
      box.appendChild(chip);
    });
    const presets = tag("div", "day-presets");
    [["Sen–Jum", "1,2,3,4,5"], ["Tiap hari", "1,2,3,4,5,6,7"]].forEach(([label, val]) => {
      const b = tag("button", "", label);
      b.type = "button";
      b.onclick = () => {
        aktif.clear();
        val.split(",").forEach((d) => aktif.add(d));
        [...box.children].forEach((c, i) => c.classList.toggle("on", aktif.has(String(i + 1))));
      };
      presets.appendChild(b);
    });
    wrap.append(box, presets);
    return { node: wrap, read: () => HARI.map(([n]) => n).filter((n) => aktif.has(String(n))).join(",") };
  }

  if (f.type === "select") {
    const sel = document.createElement("select");
    (f.options || []).forEach(([val, text]) => {
      const o = tag("option", "", text);
      o.value = val;
      sel.appendChild(o);
    });
    sel.value = String(f.value ?? "");
    wrap.appendChild(sel);
    return { node: wrap, read: () => sel.value };
  }

  const inp = document.createElement("input");
  inp.type = f.type || "text";
  inp.value = f.value ?? "";
  if (f.placeholder) inp.placeholder = f.placeholder;
  if (f.min != null) inp.min = f.min;
  if (f.max != null) inp.max = f.max;
  wrap.appendChild(inp);
  if (f.hint) wrap.appendChild(tag("p", "hint", f.hint));
  return { node: wrap, read: () => inp.value.trim(), focus: inp };
}

/** Modal berisi beberapa field sekaligus. Return objek nilai, atau null kalau dibatalkan. */
function askForm({ title, body = "", fields, ok = "Simpan" }) {
  return new Promise((resolve) => {
    el.mTitle.textContent = title;
    el.mBody.textContent = body;
    el.mInput.hidden = true;
    el.mForm.innerHTML = "";
    el.mForm.hidden = false;

    const built = [];
    let row = null;
    fields.forEach((f) => {
      const b = buildField(f);
      built.push({ key: f.key, read: b.read });
      if (f.half) {
        if (!row) { row = tag("div", "mf-row"); el.mForm.appendChild(row); }
        row.appendChild(b.node);
        if (row.children.length >= 2) row = null;
      } else {
        row = null;
        el.mForm.appendChild(b.node);
      }
    });

    el.mOk.textContent = ok;
    el.mOk.className = "primary";
    el.modal.hidden = false;
    const first = el.mForm.querySelector("input, select");
    if (first) setTimeout(() => { first.focus(); first.select?.(); }, 30);

    const done = (result) => {
      el.modal.hidden = true;
      el.mForm.hidden = true;
      el.mForm.innerHTML = "";
      el.mOk.onclick = el.mCancel.onclick = null;
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const submit = () => {
      const out = {};
      built.forEach((b) => (out[b.key] = b.read()));
      done(out);
    };
    const onKey = (e) => {
      if (e.key === "Escape") done(null);
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") { e.preventDefault(); submit(); }
    };
    el.mOk.onclick = submit;
    el.mCancel.onclick = () => done(null);
    document.addEventListener("keydown", onKey);
  });
}
