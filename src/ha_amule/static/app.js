"use strict";

// Every URL is relative so the UI works under Home Assistant's Ingress prefix.
// File names come from the eD2k network: always render them through esc() or textContent.

const I18N = {
  es: {
    transfers: "Descargas", search: "Buscar", uploads: "Subidas", shared: "Compartidos", network: "Red", log: "Registro",
    paste_links: "Pega enlaces ed2k:// (uno por línea)", add: "Añadir", all: "Todas", active: "Activas", paused: "En pausa",
    completed: "Completadas", completed_state: "Completada", filter: "Filtrar", clear_completed: "Quitar completadas", resume: "Reanudar", pause: "Pausar",
    priority: "Prioridad", prio_auto: "Automática", prio_high: "Alta", prio_normal: "Normal", prio_low: "Baja", cancel: "Cancelar",
    search_placeholder: "¿Qué estás buscando?", scope_global: "eD2k (todos los servidores)", scope_local: "eD2k (servidor actual)",
    type: "Tipo", any: "Cualquiera", video: "Vídeo", audio: "Audio", documents: "Documentos", images: "Imágenes",
    archives: "Comprimidos", cd_images: "Imágenes CD/DVD", programs: "Programas", extension: "Extensión", min_size: "Mín. MB",
    max_size: "Máx. MB", min_sources: "Mín. fuentes", stop: "Detener", download_selected: "Descargar selección", name: "Nombre",
    size: "Tamaño", sources: "Fuentes", complete: "Completas", user: "Usuario", file: "Archivo", client: "Cliente",
    speed: "Velocidad", session: "Sesión", rescan: "Volver a escanear", requests: "Peticiones", uploaded: "Subido",
    speed_limits: "Límites de velocidad", limits_hint: "kB/s, 0 = sin límite. Se aplica hasta que se reinicie la app; para fijarlo usa la configuración de la app.",
    apply: "Aplicar", servers: "Servidores", address: "Dirección", users: "Usuarios", files: "Archivos",
    downloading: "Descargando", waiting: "En cola", stopped: "Detenida", hashing: "Verificando", completing: "Finalizando",
    error: "Error", of: "de", left: "restante", connect: "Conectar", connected: "Conectado", connecting: "Conectando…",
    disconnected: "Desconectado", firewalled: "Tras cortafuegos", high_id: "ID alta", low_id: "ID baja", server: "Servidor",
    kad_running: "Iniciando…", nodes: "Nodos", no_downloads: "No hay descargas", no_downloads_hint: "Busca algo o pega un enlace ed2k.",
    no_results: "Sin resultados", searching: "Buscando…", results: "resultados", selected: "seleccionadas",
    confirm_cancel: "¿Cancelar {n} descarga(s)? Se borrarán los datos descargados.", added: "Añadido a descargas",
    no_uploads: "Nadie está descargando de ti ahora mismo", no_shared: "No hay archivos compartidos",
    lowid_hint: "Con ID baja descargas más despacio. Abre el puerto 4662/TCP y 4672/UDP en tu router hacia Home Assistant.",
    kad_fw_hint: "Kad tras cortafuegos: abre el puerto 4672/UDP en tu router hacia Home Assistant.",
    sources_short: "fuentes", eta: "quedan", users_files: "Usuarios / archivos", total_down: "Descargado (sesión)",
    total_up: "Subido (sesión)", download: "Bajada", upload: "Subida", upload_queue: "Cola de subida", shared_files: "Archivos compartidos", statistics: "Estadísticas",
    starting: "aMule se está iniciando…", in_queue: "ya en descargas", downloaded: "ya descargado", copy_link: "Copiar enlace",
    copied: "Enlace copiado", details: "Detalles", unlimited: "sin límite", last_complete: "Completo visto",
    never: "nunca", ago: "hace",
  },
};

const lang = (navigator.language || "en").slice(0, 2);
const dict = I18N[lang] || {};
const SEARCH_POLL_MS = 1500;
const EN = {
  downloading: "Downloading", waiting: "Queued", paused: "Paused", stopped: "Stopped", hashing: "Hashing",
  completing: "Completing", completed: "Completed", completed_state: "Completed", error: "Error", of: "of", connect: "Connect", connected: "Connected",
  connecting: "Connecting…", disconnected: "Disconnected", firewalled: "Firewalled", high_id: "High ID", low_id: "Low ID",
  server: "Server", kad_running: "Starting…", nodes: "Nodes", no_downloads: "No downloads",
  no_downloads_hint: "Search for something or paste an ed2k link.", no_results: "No results", searching: "Searching…",
  results: "results", selected: "selected", confirm_cancel: "Cancel {n} download(s)? Downloaded data will be deleted.",
  added: "Added to downloads", no_uploads: "Nobody is downloading from you right now", no_shared: "No shared files",
  lowid_hint: "With a low ID downloads are slower. Forward 4662/TCP and 4672/UDP on your router to Home Assistant.",
  kad_fw_hint: "Kad is firewalled: forward 4672/UDP on your router to Home Assistant.", sources_short: "sources",
  eta: "left", users_files: "Users / files", total_down: "Downloaded (session)", total_up: "Uploaded (session)",
  download: "Download", upload: "Upload", upload_queue: "Upload queue", shared_files: "Shared files", statistics: "Statistics", starting: "aMule is starting…",
  in_queue: "already downloading", downloaded: "already downloaded", copy_link: "Copy link", copied: "Link copied",
  resume: "Resume", pause: "Pause", cancel: "Cancel", details: "Details", unlimited: "unlimited",
  last_complete: "Last seen complete", never: "never", ago: "ago", prio_auto: "Auto", prio_high: "High",
  prio_normal: "Normal", prio_low: "Low", priority: "Priority",
};
const t = (key) => dict[key] || EN[key] || key;

document.documentElement.lang = I18N[lang] ? lang : "en";
document.querySelectorAll("[data-i18n]").forEach((el) => { if (dict[el.dataset.i18n]) el.textContent = dict[el.dataset.i18n]; });
document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
  if (dict[el.dataset.i18nPlaceholder]) el.placeholder = dict[el.dataset.i18nPlaceholder];
});

// -- helpers -------------------------------------------------------------------------------

const ICONS = {
  pause: "M14 19h4V5h-4M6 19h4V5H6v14Z",
  resume: "M8 5.14v14l11-7-11-7Z",
  copy: "M10.59 13.41a1 1 0 0 1 0-1.41l4-4a1 1 0 1 1 1.41 1.41l-4 4a1 1 0 0 1-1.41 0ZM7.05 20.95a4.5 4.5 0 0 1-3.18-7.68l2.12-2.12a1 1 0 1 1 1.42 1.41l-2.13 2.13a2.5 2.5 0 0 0 3.54 3.54l2.12-2.13a1 1 0 0 1 1.42 1.42l-2.13 2.12a4.48 4.48 0 0 1-3.18 1.31Zm9.07-7.68a1 1 0 0 1-.7-1.71l2.12-2.12a2.5 2.5 0 0 0-3.54-3.54l-2.12 2.13a1 1 0 0 1-1.42-1.42l2.13-2.12a4.5 4.5 0 0 1 6.36 6.36l-2.12 2.13a1 1 0 0 1-.71.29Z",
  cancel: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41Z",
  download: "M5 20h14v-2H5m14-9h-4V3H9v6H5l7 7 7-7Z",
};
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const nf = new Intl.NumberFormat(document.documentElement.lang);

function bytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  const v = n / 1024 ** i;
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}
const rate = (n) => `${bytes(n)}/s`;

function duration(sec) {
  if (!isFinite(sec) || sec <= 0) return "";
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`;
  return `${Math.floor(sec / 86400)}d ${Math.round((sec % 86400) / 3600)}h`;
}

async function api(path, options = {}) {
  const init = { ...options, headers: { "Content-Type": "application/json" } };
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  const res = await fetch(`api/${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ");
    } catch { /* not JSON */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 || res.status === 202 ? null : res.json();
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
}

async function act(promise, okMessage) {
  try {
    await promise;
    if (okMessage) toast(okMessage);
    refresh();
    return true;
  } catch (err) {
    toast(err.message, true);
    return false;
  }
}

// -- tabs -----------------------------------------------------------------------------------

let currentTab = "transfers";
let tabChanged = true;
function showTab(name) {
  currentTab = name;
  tabChanged = true;
  $$("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tab").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  try { sessionStorage.setItem("tab", name); } catch { /* storage blocked */ }
  refresh();
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) showTab(b.dataset.tab);
});

// -- overview: top bar + downloads ------------------------------------------------------------

const state = { overview: null, selected: new Set(), filter: "all", search: null, sort: { key: "sources", dir: -1 }, picked: new Set() };

function renderTop(o) {
  const c = o.status.connection;
  let ed2k;
  if (c.ed2k_connected) ed2k = `<span class="pill ${c.ed2k_high_id ? "ok" : "warn"}">eD2k · ${t(c.ed2k_high_id ? "high_id" : "low_id")}</span>`;
  else if (c.ed2k_connecting) ed2k = `<span class="pill warn">eD2k · ${t("connecting")}</span>`;
  else ed2k = `<span class="pill bad">eD2k · ${t("disconnected")}</span>`;
  let kad;
  if (c.kad_connected) kad = `<span class="pill ${c.kad_firewalled ? "warn" : "ok"}">Kad · ${t(c.kad_firewalled ? "firewalled" : "connected")}</span>`;
  else if (c.kad_running) kad = `<span class="pill warn">Kad · ${t("kad_running")}</span>`;
  else kad = `<span class="pill bad">Kad · ${t("disconnected")}</span>`;
  $("#pills").innerHTML = ed2k + kad;
  const s = o.stats;
  const lim = (n) => (n ? ` <small>/ ${rate(n)}</small>` : "");
  $("#speeds").innerHTML = `<span>↓ ${rate(s.download_speed)}${lim(s.download_limit)}</span><span>↑ ${rate(s.upload_speed)}${lim(s.upload_limit)}</span>`;
  const active = o.counts.downloading;
  $("#badge-transfers").hidden = !active;
  $("#badge-transfers").textContent = active;
}

const ACTIVE = new Set(["downloading", "waiting", "hashing", "completing"]);
function matchesFilter(d) {
  const f = state.filter;
  if (f === "active" && !ACTIVE.has(d.state)) return false;
  if (f === "paused" && d.state !== "paused" && d.state !== "stopped") return false;
  if (f === "completed" && d.state !== "completed") return false;
  const q = $("#dl-filter").value.trim().toLowerCase();
  return !q || d.name.toLowerCase().includes(q);
}

const ORDER = { downloading: 0, completing: 1, hashing: 2, waiting: 3, paused: 4, stopped: 5, error: 6, completed: 7 };

function renderDownloads(list) {
  $("#n-all").textContent = list.length;
  $("#n-active").textContent = list.filter((d) => ACTIVE.has(d.state)).length;
  $("#n-paused").textContent = list.filter((d) => d.state === "paused" || d.state === "stopped").length;
  $("#n-completed").textContent = list.filter((d) => d.state === "completed").length;
  const hashes = new Set(list.map((d) => d.hash));
  state.selected.forEach((h) => { if (!hashes.has(h)) state.selected.delete(h); });

  const shown = list.filter(matchesFilter).sort((a, b) => ORDER[a.state] - ORDER[b.state] || b.speed - a.speed || a.name.localeCompare(b.name));
  const box = $("#downloads");
  if (!shown.length) {
    box.innerHTML = `<div class="card empty"><b>${t("no_downloads")}</b>${list.length ? "" : t("no_downloads_hint")}</div>`;
  } else {
    box.innerHTML = shown.map((d) => {
      const left = d.speed > 0 ? duration((d.size - d.done) / d.speed) : "";
      const barClass = d.state === "completed" ? "done" : d.state === "error" ? "error" : d.state === "paused" || d.state === "stopped" ? "paused" : "";
      const canResume = d.state === "paused" || d.state === "stopped";
      const finished = d.state === "completed";
      return `<div class="card dl${state.selected.has(d.hash) ? " selected" : ""}" data-hash="${esc(d.hash)}">
        <input type="checkbox" data-select ${state.selected.has(d.hash) ? "checked" : ""} aria-label="Select" ${finished ? "disabled" : ""}>
        <div class="name">${esc(d.name)}</div>
        <div class="bar ${barClass}"><div style="width:${d.progress}%"></div></div>
        <div class="meta">
          <span class="state ${d.state}">${t(finished ? "completed_state" : d.state)}</span>
          <span>${d.progress.toFixed(1)}% · ${bytes(d.done)} ${t("of")} ${bytes(d.size)}</span>
          ${d.speed ? `<span>↓ ${rate(d.speed)}</span>` : ""}
          ${left ? `<span>${left} ${t("eta")}</span>` : ""}
          ${finished ? "" : `<span>${d.sources_transferring}/${d.sources} ${t("sources_short")}</span>`}
          ${finished ? "" : `<span title="${t("priority")}">${t(`prio_${d.priority}`)}${d.auto_priority ? " (auto)" : ""}</span>`}
        </div>
        <div class="buttons">
          ${finished ? "" : canResume
            ? `<button class="icon" data-act="resume" title="${t("resume")}" aria-label="${t("resume")}">${icon("resume")}</button>`
            : `<button class="icon" data-act="pause" title="${t("pause")}" aria-label="${t("pause")}">${icon("pause")}</button>`}
          <button class="icon" data-act="copy" title="${t("copy_link")}" aria-label="${t("copy_link")}">${icon("copy")}</button>
          ${finished ? "" : `<button class="icon" data-act="cancel" title="${t("cancel")}" aria-label="${t("cancel")}">${icon("cancel")}</button>`}
        </div>
      </div>`;
    }).join("");
  }
  renderSelection();
}

function renderSelection() {
  const n = state.selected.size;
  $("#selection").hidden = n === 0;
  $("#selection-count").textContent = `${n} ${t("selected")}`;
}

function confirmCancel(hashes) {
  return window.confirm(t("confirm_cancel").replace("{n}", hashes.length));
}

$("#downloads").addEventListener("click", async (e) => {
  const card = e.target.closest(".dl");
  if (!card) return;
  const hash = card.dataset.hash;
  if (e.target.matches("[data-select]")) {
    if (e.target.checked) state.selected.add(hash); else state.selected.delete(hash);
    card.classList.toggle("selected", e.target.checked);
    renderSelection();
    return;
  }
  const button = e.target.closest("button[data-act]");
  if (!button) return;
  const action = button.dataset.act;
  if (action === "copy") {
    const d = state.overview.downloads.find((x) => x.hash === hash);
    try { await navigator.clipboard.writeText(d.link); toast(t("copied")); } catch { window.prompt("ed2k", d.link); }
    return;
  }
  if (action === "cancel" && !confirmCancel([hash])) return;
  act(api(`downloads/${action}`, { method: "POST", body: { hashes: [hash] } }));
});

$("#selection").addEventListener("click", async (e) => {
  const action = e.target.dataset.bulk;
  if (!action) return;
  const hashes = [...state.selected];
  if (action === "cancel" && !confirmCancel(hashes)) return;
  if (await act(api(`downloads/${action}`, { method: "POST", body: { hashes } }))) {
    state.selected.clear();
    renderSelection();
  }
});

$("#bulk-priority").addEventListener("change", async (e) => {
  const priority = e.target.value;
  if (!priority) return;
  await act(api("downloads/priority", { method: "POST", body: { hashes: [...state.selected], priority } }));
  e.target.value = "";
});

$("#filters").addEventListener("click", (e) => {
  const chip = e.target.closest("[data-filter]");
  if (!chip) return;
  state.filter = chip.dataset.filter;
  $$("#filters .chip").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
  if (state.overview) renderDownloads(state.overview.downloads);
});
$("#dl-filter").addEventListener("input", () => state.overview && renderDownloads(state.overview.downloads));
$("#clear-completed").addEventListener("click", () => act(api("downloads/clear-completed", { method: "POST" })));

const links = $("#links");
links.addEventListener("input", () => { links.rows = Math.min(8, Math.max(1, links.value.split("\n").length)); });
links.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#add-form").requestSubmit();
});
$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const list = links.value.split(/\s*\n\s*/).map((l) => l.trim()).filter(Boolean);
  if (!list.length) return;
  if (await act(api("downloads", { method: "POST", body: { links: list } }), t("added"))) {
    links.value = "";
    links.rows = 1;
  }
});

// -- search -----------------------------------------------------------------------------------

function sortedResults() {
  const { key, dir } = state.sort;
  const q = $("#res-filter").value.trim().toLowerCase();
  const rows = (state.search?.results || []).filter((r) => !q || r.name.toLowerCase().includes(q));
  return rows.sort((a, b) => (key === "name" ? a.name.localeCompare(b.name) : a[key] - b[key]) * dir);
}

function renderSearch() {
  const s = state.search;
  if (!s) return;
  $("#search-progress").hidden = !s.running;
  $("#stop-search").hidden = !s.running;
  $("#search-btn").disabled = s.running;
  $("#search-info").textContent = s.running
    ? `${t("searching")} ${s.progress ? `${s.progress}%` : ""} · ${nf.format(s.results.length)} ${t("results")}`
    : s.results.length ? `${nf.format(s.results.length)} ${t("results")}` : "";
  const known = new Set(s.results.map((r) => r.hash));
  state.picked.forEach((h) => { if (!known.has(h)) state.picked.delete(h); });
  const rows = sortedResults();
  $("#results tbody").innerHTML = rows.length ? rows.map((r) => {
    const isKnown = r.known !== "new";
    const label = r.known === "downloaded" ? t("downloaded") : isKnown ? t("in_queue") : "";
    return `<tr class="${isKnown ? "known" : ""}" data-hash="${esc(r.hash)}">
      <td class="check"><input type="checkbox" data-pick ${state.picked.has(r.hash) ? "checked" : ""} ${isKnown ? "disabled" : ""} aria-label="Select"></td>
      <td class="name">${esc(r.name)}${label ? `<span class="tag">${label}</span>` : ""}</td>
      <td class="num">${bytes(r.size)}</td>
      <td class="num">${nf.format(r.sources)}</td>
      <td class="num">${nf.format(r.complete_sources)}</td>
      <td class="num">${isKnown ? "" : `<button class="icon" data-download title="Download" aria-label="Download">${icon("download")}</button>`}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="6" class="empty">${s.running ? t("searching") : t("no_results")}</td></tr>`;
  $$("#results th[data-sort]").forEach((th) => {
    th.classList.toggle("asc", th.dataset.sort === state.sort.key && state.sort.dir === 1);
    th.classList.toggle("desc", th.dataset.sort === state.sort.key && state.sort.dir === -1);
  });
  $("#download-selected").disabled = state.picked.size === 0;
  $("#download-selected").textContent = `${dict.download_selected || "Download selected"}${state.picked.size ? ` (${state.picked.size})` : ""}`;
}

let searchTimer;
async function pollSearch() {
  clearTimeout(searchTimer);
  try {
    state.search = await api("search");
    renderSearch();
  } catch (err) {
    if (err.status !== 503) toast(err.message, true);
  }
  if (state.search?.running) searchTimer = setTimeout(pollSearch, SEARCH_POLL_MS);
}

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mb = (id) => Math.max(0, Math.round(Number($(id).value || 0) * 1024 * 1024));
  const body = {
    query: $("#q").value.trim(),
    scope: $("#scope").value,
    file_type: $("#ftype").value,
    extension: $("#ext").value.trim(),
    min_size: mb("#minsize"),
    max_size: mb("#maxsize"),
    availability: Math.max(0, Number($("#avail").value || 0)),
  };
  try {
    await api("search", { method: "POST", body });
    state.picked.clear();
    state.search = { running: true, progress: 0, results: [] };
    renderSearch();
    searchTimer = setTimeout(pollSearch, 1000);
  } catch (err) {
    toast(err.message, true);
  }
});
$("#stop-search").addEventListener("click", async () => { await act(api("search", { method: "DELETE" })); pollSearch(); });
$("#res-filter").addEventListener("input", renderSearch);
$("#results thead").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]");
  if (!th) return;
  const key = th.dataset.sort;
  state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : key === "name" ? 1 : -1 };
  renderSearch();
});
$("#select-all-results").addEventListener("change", (e) => {
  sortedResults().filter((r) => r.known === "new").forEach((r) => (e.target.checked ? state.picked.add(r.hash) : state.picked.delete(r.hash)));
  renderSearch();
});
$("#results tbody").addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-hash]");
  if (!row) return;
  if (e.target.matches("[data-pick]")) {
    if (e.target.checked) state.picked.add(row.dataset.hash); else state.picked.delete(row.dataset.hash);
    renderSearch();
  } else if (e.target.closest("[data-download]")) {
    if (await act(api("search/download", { method: "POST", body: { hashes: [row.dataset.hash] } }), t("added"))) pollSearch();
  }
});
$("#download-selected").addEventListener("click", async () => {
  if (await act(api("search/download", { method: "POST", body: { hashes: [...state.picked] } }), t("added"))) {
    state.picked.clear();
    $("#select-all-results").checked = false;
    pollSearch();
  }
});

// -- uploads, shared, network, log ------------------------------------------------------------

async function loadUploads() {
  const list = await api("uploads");
  $("#badge-uploads").hidden = !list.length;
  $("#badge-uploads").textContent = list.length;
  $("#uploads tbody").innerHTML = list.length ? list.map((u) => `<tr>
    <td>${esc(u.user)}</td><td class="name">${esc(u.file)}</td><td>${esc(u.client)}</td>
    <td class="num">${rate(u.speed)}</td><td class="num">${bytes(u.session)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">${t("no_uploads")}</td></tr>`;
}

let sharedCache = [];
function renderShared() {
  const q = $("#shared-filter").value.trim().toLowerCase();
  const list = sharedCache.filter((f) => !q || f.name.toLowerCase().includes(q));
  $("#shared-info").textContent = `${nf.format(sharedCache.length)} · ${bytes(sharedCache.reduce((a, f) => a + f.size, 0))}`;
  $("#shared tbody").innerHTML = list.length ? list.map((f) => `<tr data-link="${esc(f.link)}">
    <td class="name">${esc(f.name)}</td><td class="num">${bytes(f.size)}</td>
    <td class="num">${nf.format(f.requests)}</td><td class="num">${bytes(f.transferred_all)}</td>
    <td class="num"><button class="icon" data-copy title="${t("copy_link")}" aria-label="${t("copy_link")}">${icon("copy")}</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">${t("no_shared")}</td></tr>`;
}
async function loadShared() {
  sharedCache = await api("shared");
  renderShared();
}
$("#shared-filter").addEventListener("input", renderShared);
$("#shared tbody").addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-link]");
  if (!row || !e.target.closest("[data-copy]")) return;
  try { await navigator.clipboard.writeText(row.dataset.link); toast(t("copied")); } catch { window.prompt("ed2k", row.dataset.link); }
});
$("#reload-shared").addEventListener("click", () => act(api("shared/reload", { method: "POST" })).then(loadShared));

function switchHtml(id, on) {
  return `<label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><span></span></label>`;
}

function renderNetwork(o) {
  const c = o.status.connection;
  const s = o.stats;
  const srv = c.server;
  $("#net-ed2k").innerHTML = `
    <div class="head"><h3>eD2k</h3>${switchHtml("sw-ed2k", c.ed2k_connected || c.ed2k_connecting)}</div>
    <dl class="kv">
      <dt>${t("connected")}</dt><dd>${c.ed2k_connected ? `${t(c.ed2k_high_id ? "high_id" : "low_id")} (${c.ed2k_id})` : t(c.ed2k_connecting ? "connecting" : "disconnected")}</dd>
      ${srv ? `<dt>${t("server")}</dt><dd>${esc(srv.name)}<br><span class="muted">${esc(srv.address)}</span></dd>` : ""}
      <dt>${t("users_files")}</dt><dd>${nf.format(s.ed2k_users)} / ${nf.format(s.ed2k_files)}</dd>
    </dl>
    ${c.ed2k_connected && !c.ed2k_high_id ? `<p class="hint">${t("lowid_hint")}</p>` : ""}`;
  $("#net-kad").innerHTML = `
    <div class="head"><h3>Kad</h3>${switchHtml("sw-kad", c.kad_running)}</div>
    <dl class="kv">
      <dt>${t("connected")}</dt><dd>${c.kad_connected ? t(c.kad_firewalled ? "firewalled" : "connected") : t(c.kad_running ? "kad_running" : "disconnected")}</dd>
      <dt>${t("nodes")}</dt><dd>${nf.format(s.kad_nodes)}</dd>
      <dt>${t("users_files")}</dt><dd>${nf.format(s.kad_users)} / ${nf.format(s.kad_files)}</dd>
    </dl>
    ${c.kad_connected && c.kad_firewalled ? `<p class="hint">${t("kad_fw_hint")}</p>` : ""}`;
  $("#net-stats").innerHTML = `<h3>${t("statistics")}</h3><dl class="kv">
    <dt>${t("total_down")}</dt><dd>${bytes(s.total_received)}</dd>
    <dt>${t("total_up")}</dt><dd>${bytes(s.total_sent)}</dd>
    <dt>${t("upload_queue")}</dt><dd>${nf.format(s.upload_queue)}</dd>
    <dt>${t("shared_files")}</dt><dd>${nf.format(s.shared_files)}</dd>
    <dt>${t("sources")}</dt><dd>${nf.format(s.sources)}</dd></dl>`;
  const down = $("#lim-down");
  const up = $("#lim-up");
  if (document.activeElement !== down && document.activeElement !== up) {
    down.value = Math.round(s.download_limit / 1024);
    up.value = Math.round(s.upload_limit / 1024);
  }
}

$("#tab-network").addEventListener("change", (e) => {
  if (e.target.id === "sw-ed2k") act(api("network/ed2k", { method: "POST", body: { enabled: e.target.checked } }));
  if (e.target.id === "sw-kad") act(api("network/kad", { method: "POST", body: { enabled: e.target.checked } }));
});
$("#limits-form").addEventListener("submit", (e) => {
  e.preventDefault();
  act(api("limits", { method: "POST", body: { download_kbps: Number($("#lim-down").value || 0), upload_kbps: Number($("#lim-up").value || 0) } }), "OK");
  document.activeElement.blur();
});

async function loadServers() {
  const list = await api("servers");
  const current = state.overview?.status.connection.server?.address;
  list.sort((a, b) => b.users - a.users);
  $("#servers tbody").innerHTML = list.map((s) => `<tr data-address="${esc(s.address)}">
    <td class="name">${esc(s.name)}${s.address === current ? `<span class="tag">${t("connected")}</span>` : ""}<br><span class="muted">${esc(s.description)}</span></td>
    <td>${esc(s.address)}</td><td class="num">${nf.format(s.users)}</td><td class="num">${nf.format(s.files)}</td>
    <td class="num">${s.ping || ""}</td>
    <td class="num">${s.address === current ? "" : `<button class="ghost" data-connect>${t("connect")}</button>`}</td></tr>`).join("");
}
$("#servers tbody").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-address]");
  if (row && e.target.closest("[data-connect]")) act(api("network/ed2k/connect", { method: "POST", body: { address: row.dataset.address } }));
});

async function loadLog() {
  const lines = await api("log");
  const box = $("#log");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  box.innerHTML = lines.map((l) => (l.startsWith("!") || /ERROR|WARNING/.test(l) ? `<span class="err">${esc(l)}</span>` : esc(l))).join("\n");
  if (atBottom) box.scrollTop = box.scrollHeight;
}

// -- refresh loop ------------------------------------------------------------------------------

let refreshing = false;
let slowTick = 0;
async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const o = await api("overview");
    state.overview = o;
    $("#banner").hidden = !o.status.error;
    $("#banner").textContent = o.status.error || "";
    renderTop(o);
    if (currentTab === "transfers") renderDownloads(o.downloads);
    const slow = tabChanged || slowTick % 5 === 0;
    tabChanged = false;
    if (currentTab === "network") {
      renderNetwork(o);
      if (slow) await loadServers();
    }
    if (currentTab === "uploads" || slow) await loadUploads();
    if (currentTab === "shared" && slow) await loadShared();
    if (currentTab === "log") await loadLog();
    if (currentTab === "search" && !state.search) await pollSearch();
  } catch (err) {
    $("#banner").hidden = false;
    $("#banner").textContent = err.status === 503 ? (err.message || t("starting")) : err.message;
  } finally {
    refreshing = false;
    slowTick += 1;
  }
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
setInterval(refresh, 2000);

let initial = "transfers";
try { initial = sessionStorage.getItem("tab") || initial; } catch { /* storage blocked */ }
showTab($(`#tabs button[data-tab="${initial}"]`) ? initial : "transfers");
