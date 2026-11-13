const $ = (s) => document.querySelector(s);
const api = async (url, opts = {}) => {
  const r = await fetch(url, opts.body ? { method: "POST", headers: { "Content-Type": "application/json" }, ...opts, body: JSON.stringify(opts.body) } : opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const PAGE = 200;
const savedSort = (() => { try { return localStorage.getItem("sort") || "relevancia"; } catch { return "relevancia"; } })();
// por padrão só aparecem arquivos de discos conectados (dá para desmarcar na lateral)
const savedOnline = (() => { try { return localStorage.getItem("onlyOnline") !== "0"; } catch { return true; } })();
const state = { people: [], peopleMode: "juntas", sort: savedSort, q: "", mode: "auto", kind: "", volume: null, tags: [], dateFrom: "", dateTo: "", camera: "", onlyOnline: savedOnline, similar: null, similarName: "" };
let items = [], total = 0, volumes = [], selected = new Set(), current = null, lastClicked = null;

// ------------------------------------------------------------ busca
function params(offset) {
  const p = new URLSearchParams({ q: state.q, mode: state.mode, kind: state.kind, tag: state.tags.join(","),
    date_from: state.dateFrom, date_to: state.dateTo, camera: state.camera, only_online: state.onlyOnline,
    limit: PAGE, offset, sort: state.sort });
  if (state.volume) p.set("volume", state.volume);
  if (state.favorite) p.set("favorite", "true");
  if (state.photo) p.set("foto", state.photo.token);
  if (state.area) p.set("area", state.area);
  if (state.album) p.set("album", state.album.key);
  if (state.review) p.set("revisar", "true");
  if (state.collection) p.set("collection", state.collection);
  peopleParams(p);
  if (state.similar) p.set("similar", state.similar);
  return p;
}

let searchSeq = 0;
async function load(append = false) {
  const seq = ++searchSeq;
  const offset = append ? items.length : 0;
  if (!append) { loadTimeline(); loadMap(); }  // linha do tempo e mapa acompanham os filtros
  $("#count").textContent = "buscando…";
  if (!append) $("#grid").classList.add("loading");
  const res = await api("/api/search?" + params(offset)).finally(() => { if (seq === searchSeq) $("#grid").classList.remove("loading"); });
  if (seq !== searchSeq) return;
  items = append ? items.concat(res.items) : res.items;
  total = res.total;
  render(append ? res.items : null);
  checkExists(res.items.map((i) => i.id), seq);
}

// depois de mostrar, confere em segundo plano se os arquivos ainda existem; os apagados somem da tela
async function checkExists(ids, seq) {
  if (!ids.length) return;
  let r;
  try { r = await api("/api/conferir", { body: { ids } }); } catch { return; }
  if (seq !== searchSeq || !r.gone.length) return;
  const gone = new Set(r.gone);
  items = items.filter((it) => !gone.has(it.id));
  total = Math.max(0, total - gone.size);
  gone.forEach((id) => { selected.delete(id); document.querySelector(`.tile[data-id="${id}"]`)?.remove(); });
  $("#count").textContent = total ? `${total.toLocaleString("pt-BR")} resultado${total > 1 ? "s" : ""}` : "";
  refreshSide();
}

function fmtDur(s) {
  if (!s) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function fmtTime(s) {
  s = Math.floor(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function tileHtml(it) {
  const badge = (it.kind === "video" ? `<span class="badge">▶ ${fmtDur(it.duration)}</span>` : "")
    + (state.review && it.review && it.review !== "kept" ? `<span class="badge rev">${REVIEW_REASON[it.review] || it.review}</span>` : "")
    + (it.sound_start != null && it.match_start == null ? `<span class="badge said" title="Som mais forte">${esc(it.sound_label)} ${fmtTime(it.sound_start)}${it.sound_count > 1 ? ` · ${it.sound_count}×` : ""}</span>` : "")
    + (it.match_start != null ? `<span class="badge said" title="${esc(it.match_text)}">🗣 ${fmtTime(it.match_start)}${it.matches > 1 ? ` · ${it.matches}×` : ""}</span>` : "");
  return `<div class="tile${selected.has(it.id) ? " sel" : ""}" data-id="${it.id}" title="${esc(it.name)}" tabindex="0" role="button" aria-label="${esc(it.name)}">
    ${it.has_thumb ? `<img loading="lazy" src="/api/thumb/${it.id}" alt="">`
      : `<div class="nothumb"><span>${it.kind === "video" ? "🎬" : "🖼️"}</span>${esc(it.name)}<small>aguardando indexação</small></div>`}${badge}
    <button class="explore" data-explore="${it.id}" title="Mostrar no Explorer">📂</button>
    <button class="star${it.favorite ? " on" : ""}" data-star="${it.id}" title="${it.favorite ? "Tirar dos favoritos" : "Favoritar"}">${it.favorite ? "★" : "☆"}</button>
    <button class="pick" data-pick="${it.id}" title="Selecionar (Shift = vários em sequência)" aria-label="Selecionar">✓</button>
    <span class="cap">${esc(it.name)}</span></div>`;
}

function render(appended) {
  const grid = $("#grid");
  if (dateOrdered()) {
    if (appended) {
      const prev = items[items.length - appended.length - 1];
      grid.insertAdjacentHTML("beforeend", withDayHeads(appended, prev ? dayOf(prev) : ""));
    } else grid.innerHTML = withDayHeads(items, "");
  } else if (appended) grid.insertAdjacentHTML("beforeend", appended.map(tileHtml).join(""));
  else grid.innerHTML = items.map(tileHtml).join("");
  $("#count").textContent = total ? `${total.toLocaleString("pt-BR")} resultado${total > 1 ? "s" : ""}` : "";
  $("#count").classList.remove("muted");
  $("#more").classList.toggle("hidden", items.length >= total);
  const empty = $("#empty");
  const noCatalog = !volumes.some((v) => v.files);
  empty.classList.toggle("hidden", items.length > 0);
  empty.innerHTML = noCatalog
    ? `O catálogo está vazio.<br><br><button onclick="openIndex()">Indexar meu primeiro disco</button>`
    : `<b>Nada encontrado.</b><br>Tente outra palavra${activeCount() ? ", ou tire algum filtro." : "."}`
      + (activeCount() ? `<br><br><button class="ghost" onclick="clearAllFilters()">Limpar todos os filtros</button>` : "")
      + (state.mode !== "auto" ? `<br><br><button class="ghost" onclick="setMode('auto')">Buscar em tudo</button>` : "");
  renderActive();
  if (selectMode) syncSelection();  // atualiza "Selecionar todos os N visíveis"
}

function renderActive() {
  const pills = [];
  if (state.favorite) pills.push(["favorite", "favoritos"]);
  if (state.photo) pills.push(["photo", "pessoa da foto enviada"]);
  if (state.area) pills.push(["area", "área do mapa"]);
  if (state.album) pills.push(["album", state.album.title]);
  if (state.review) pills.push(["review", "para revisar"]);
  if (state.people.length) pills.push(["people", peopleLabel()]);
  if (state.similar) pills.push(["similar", `parecidos com ${state.similarName}`]);
  state.tags.forEach((t) => pills.push(["tag:" + t, t]));
  if (state.volume) pills.push(["volume", volumes.find((v) => v.id === state.volume)?.label || "disco"]);
  if (state.camera) pills.push(["camera", state.camera]);
  const br = (d) => d ? d.split("-").reverse().join("/") : "…";
  if (state.dateFrom || state.dateTo) pills.push(["date", `${br(state.dateFrom)} até ${br(state.dateTo)}`]);
  const n = pills.length + (state.kind ? 1 : 0);
  $("#clearAll").classList.toggle("hidden", pills.length < 2);
  $("#filterBadge").textContent = n;
  $("#filterBadge").classList.toggle("hidden", !n);
  $("#activeFilters").innerHTML = pills.map(([k, l]) => k === "photo"
    ? `<span class="pill photo" data-k="photo" title="${esc(l)}"><img src="${state.photo.preview}" alt=""><span class="t">${esc(l)}</span></span>`
    : `<span class="pill" data-k="${esc(k)}" title="${esc(l)}"><span class="t">${esc(l)}</span></span>`).join("");
}

$("#activeFilters").addEventListener("click", (e) => {
  const k = e.target.dataset.k;
  if (!k) return;
  if (k === "similar") state.similar = null;
  else if (k === "favorite") state.favorite = false;
  else if (k === "photo") state.photo = null;
  else if (k === "area") state.area = "";
  else if (k === "album") state.album = null;
  else if (k === "review") state.review = false;
  else if (k === "people") state.people = [];
  else if (k.startsWith("tag:")) state.tags = state.tags.filter((t) => t !== k.slice(4));
  else if (k === "volume") state.volume = null;
  else if (k === "camera") { state.camera = ""; $("#camera").value = ""; }
  else if (k === "date") {
    state.dateFrom = state.dateTo = ""; $("#dateFrom").value = $("#dateTo").value = "";
    tl.year = tl.month = tl.day = "";
  }
  refreshSide(); load();
});

let typingTimer;
$("#q").addEventListener("input", () => {
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => { state.q = $("#q").value; state.similar = null; state.photo = null; load(); }, 350);
});
$("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); state.q = $("#q").value; state.similar = null; state.photo = null; load(); });
function setMode(m) {
  state.mode = m; $("#mode").value = m;
  document.querySelectorAll("#modeChips button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === m); b.setAttribute("aria-checked", b.dataset.mode === m);
  });
  const ph = { auto: "Buscar: “criança na praia”, “bolo de aniversário”…", texto: "Palavras exatas do nome ou das palavras-chave",
    escrito: "Texto escrito na foto: placa, banner, camiseta…", falado: "O que foi dito nos vídeos",
    som: "Sons: aplausos, fogos, música, torcida…" }[m];
  $("#q").placeholder = ph;
  load();
}
$("#mode").addEventListener("change", (e) => setMode(e.target.value));
$("#modeChips").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); });
$("#sort").value = state.sort;
$("#sort").addEventListener("change", (e) => {
  state.sort = e.target.value;
  try { localStorage.setItem("sort", state.sort); } catch {}
  load();
});
$("#kindSeg").addEventListener("click", (e) => {
  if (!e.target.dataset || e.target.dataset.kind === undefined) return;
  state.kind = e.target.dataset.kind;
  document.querySelectorAll("#kindSeg button").forEach((b) => b.classList.toggle("on", b === e.target));
  load();
});
$("#onlyOnline").checked = state.onlyOnline;
$("#onlyOnline").addEventListener("change", (e) => {
  state.onlyOnline = e.target.checked;
  try { localStorage.setItem("onlyOnline", state.onlyOnline ? "1" : "0"); } catch {}
  load();
});
$("#dateFrom").addEventListener("change", (e) => { state.dateFrom = e.target.value; load(); });
$("#dateTo").addEventListener("change", (e) => { state.dateTo = e.target.value; load(); });
$("#camera").addEventListener("change", (e) => { state.camera = e.target.value; load(); });
$("#more button").addEventListener("click", () => load(true));
// rolagem infinita: ao chegar perto do fim da lista, carrega mais sozinho (útil no celular)
let loadingMore = false;
window.addEventListener("scroll", async () => {
  if (loadingMore || $("#more").classList.contains("hidden")) return;
  if (window.innerHeight + window.scrollY < document.documentElement.scrollHeight - 800) return;
  loadingMore = true;
  try { await load(true); } finally { loadingMore = false; }
}, { passive: true });

// ------------------------------------------------------------ barra lateral
async function refreshSide() {
  refreshReview();
  refreshColls();
  volumes = await api("/api/volumes");
  $("#volumes").innerHTML = volumes.map((v) => `
    <div class="vol${state.volume === v.id ? " on" : ""}" data-id="${v.id}" title="${v.online ? "Conectado em " + v.letter + ":" : "Desconectado"}">
      <span class="dot${v.online ? " online" : ""}"></span>
      <span class="name">${esc(v.label)}</span><small>${(v.files || 0).toLocaleString("pt-BR")}</small>
    </div>`).join("") || `<div class="muted">Nenhum disco indexado.</div>`;

  const tags = await api("/api/tags?limit=60");
  $("#tagCloud").innerHTML = tags.map((t) => `<span class="${state.tags.includes(t.name) ? "on" : ""}" data-t="${esc(t.name)}" tabindex="0" role="button">${esc(t.name)}<small>${t.n}</small></span>`).join("");
  $("#tagMore").classList.toggle("hidden", tags.length <= 20);
  filterTags();
  $("#tagList").innerHTML = tags.map((t) => `<option value="${esc(t.name)}">`).join("");

  const cams = await api("/api/cameras");
  const cur = $("#camera").value;
  $("#camera").innerHTML = `<option value="">Todas</option>` + cams.map((c) => `<option>${esc(c)}</option>`).join("");
  $("#camera").value = cur;
}
$("#volumes").addEventListener("click", (e) => {
  const el = e.target.closest(".vol");
  if (!el) return;
  const id = Number(el.dataset.id);
  state.volume = state.volume === id ? null : id;
  const vol = volumes.find((v) => v.id === id);
  if (state.volume && vol && !vol.online && state.onlyOnline) {
    // você pediu explicitamente um disco desconectado: mostra o catálogo dele mesmo assim
    state.onlyOnline = false; $("#onlyOnline").checked = false;
    toast(`Mostrando o catálogo de ${vol.label}, que está desconectado (só as miniaturas).`);
  }
  refreshSide(); load();
});
$("#tagCloud").addEventListener("click", (e) => {
  const t = e.target.closest("span")?.dataset.t;
  if (!t) return;
  state.tags = state.tags.includes(t) ? state.tags.filter((x) => x !== t) : [...state.tags, t];
  refreshSide(); load();
});

// ------------------------------------------------------------ grade e seleção
async function showInExplorer(id) {
  try {
    await api(`/api/open/${id}?folder=true`, { method: "POST" });
  } catch (err) {
    toast(err.message === "disco desconectado" ? "O disco deste arquivo está desconectado." : err.message);
  }
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

$("#grid").addEventListener("click", (e) => {
  if (e.target.dataset.explore) {
    showInExplorer(Number(e.target.dataset.explore));
    return;
  }
  if (e.target.dataset.star) {
    const it = items.find((x) => x.id === Number(e.target.dataset.star));
    setFavorite([it.id], !it.favorite);
    return;
  }
  const tile = e.target.closest(".tile");
  if (!tile) return;
  const id = Number(tile.dataset.id);
  // modo de seleção (botão "Selecionar" ou o ✓ da miniatura): clicar marca/desmarca em vez de abrir
  if (selectMode || e.target.dataset.pick || e.ctrlKey || e.metaKey || e.shiftKey) {
    if (e.shiftKey && lastClicked != null) {
      const ids = items.map((i) => i.id);
      const [a, b] = [ids.indexOf(lastClicked), ids.indexOf(id)].sort((x, y) => x - y);
      ids.slice(a, b + 1).forEach((x) => selected.add(x));
    } else if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    lastClicked = id;
    selectMode = true;
    syncSelection();
    return;
  }
  openViewer(id);
});

let selectMode = false;
function syncSelection() {
  document.body.classList.toggle("selecting", selectMode);
  document.querySelectorAll(".tile").forEach((t) => t.classList.toggle("sel", selected.has(Number(t.dataset.id))));
  $("#selBar").classList.toggle("hidden", !selectMode);
  const n = selected.size;
  $("#selCount").textContent = n ? `${n.toLocaleString("pt-BR")} selecionado${n > 1 ? "s" : ""}` : "Clique nas miniaturas para selecionar";
  $("#bulkPremiere").textContent = n ? `Importar ${n.toLocaleString("pt-BR")} no Premiere` : "Importar no Premiere";
  ["#bulkPremiere", "#bulkAdd", "#bulkFav", "#bulkColl", "#bulkUncoll", "#bulkXmp", "#bulkDown", "#bulkToPhone", "#bulkKeep", "#bulkReviewTrash"].forEach((s) => { $(s).disabled = !n; });
  document.querySelectorAll(".review-only").forEach((b) => b.classList.toggle("hidden", !state.review));
  $("#btnSelect").innerHTML = selectMode ? "Concluir" : `<span class="lbl">Selecionar</span>`;
  $("#btnSelectAll").classList.toggle("hidden", !selectMode);
  $("#btnSelectAll").textContent = `Todos (${items.length.toLocaleString("pt-BR")})`;
  $("#btnSelectAll").title = `Seleciona os ${items.length} resultados carregados na tela`;
}
$("#selClear").addEventListener("click", () => { selected.clear(); selectMode = false; syncSelection(); });
$("#btnSelect").addEventListener("click", () => {
  selectMode = !selectMode;
  if (!selectMode) selected.clear();
  syncSelection();
});
$("#btnSelectAll").addEventListener("click", () => {
  items.forEach((it) => selected.add(it.id));
  syncSelection();
});
$("#bulkAdd").addEventListener("click", async () => {
  const names = $("#bulkTag").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!names.length) return;
  await api("/api/tags/bulk", { body: { ids: [...selected], add: names } });
  $("#bulkTag").value = "";
  selected.clear(); syncSelection(); refreshSide();
});
$("#bulkTag").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#bulkAdd").click(); });

// ------------------------------------------------------------ visualizador
async function openViewer(id) {
  current = await api(`/api/file/${id}`);
  const f = current;
  $("#viewer").classList.remove("hidden");
  $("#vname").textContent = f.name;
  $("#vpath").textContent = f.full_path;
  const media = $("#vmedia");
  if (!f.online) {
    media.innerHTML = `<div class="offline"><img src="/api/thumb/${f.id}"><div>Disco <b>${esc(f.volume)}</b> desconectado.<br>Conecte-o para abrir o arquivo original.</div></div>`;
  } else if (f.kind === "video" && !f.has_thumb) {
    media.innerHTML = `<video src="/api/media/${f.id}" controls></video>`;
  } else if (f.kind === "video") {
    // vindo de uma busca pelo que foi dito, já abre no momento da fala
    const found = items.find((x) => x.id === f.id);
    const hit = found?.match_start ?? found?.sound_start;
    const start = hit != null ? Math.max(0, hit - 1) : 0;
    const t = start ? `#t=${start.toFixed(1)}` : "";
    media.innerHTML = `<video src="/api/media/${f.id}${t}" controls autoplay playsinline poster="/api/thumb/${f.id}"></video>`
      + (document.body.classList.contains("remote") ? `<button class="ghost light-btn" id="vlight">▶ Versão leve (se o vídeo não tocar)</button>` : "");
    const v = media.querySelector("video");
    // o navegador não toca esse formato (ex.: HEVC 10 bits no celular): o PC converte na hora
    v.addEventListener("error", () => playLight(start), { once: true });
    $("#vlight")?.addEventListener("click", () => playLight(v.currentTime || start));
  } else if ([".heic", ".heif", ".tif", ".tiff"].includes(f.ext)) {
    media.innerHTML = `<img src="/api/thumb/${f.id}">`;  // navegador não abre esses formatos
  } else {
    media.innerHTML = `<img src="/api/media/${f.id}">`;
  }
  const rows = [
    ["Disco", `${f.volume}${f.online ? "" : " (desconectado)"}`],
    ["Data", f.taken_at ? new Date(f.taken_at).toLocaleString("pt-BR") : ""],
    ["Tamanho", f.width ? `${f.width} × ${f.height}` : ""],
    ["Duração", fmtDur(f.duration)],
    ["Câmera", f.camera],
    ["Arquivo", f.size ? (f.size / 1048576).toFixed(1) + " MB" : ""],
    ["GPS", f.gps_lat ? `<a href="https://www.google.com/maps?q=${f.gps_lat},${f.gps_lon}" target="_blank" rel="noopener">ver no mapa</a>` : ""],
  ].filter(([, v]) => v);
  $("#vmeta").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${k === "GPS" ? v : esc(v)}</dd>`).join("");
  $("#vdesc").classList.toggle("hidden", !f.descricao);
  $("#vdesc").textContent = f.descricao || "";
  renderTags();
  renderFaces();
  renderMarks();
  renderDownload();
  renderSpeech();
  renderSounds();
  $("#vpremiere").disabled = !f.online;
  $("#vpremiereCut").classList.toggle("hidden", !(f.online && speechQuery() && $("#vspeech .seg.hit")));
  $("#vocrWrap").classList.toggle("hidden", !f.ocr_text);
  $("#vocr").innerHTML = highlight(f.ocr_text || "", state.mode === "escrito" ? state.q : "");
  $("#vopen").disabled = $("#vfolder").disabled = !f.online;
  $("#vframes").innerHTML = f.kind === "video"
    ? Array.from({ length: f.frames }, (_, i) => `<img src="/api/thumb/${f.id}?frame=${i}" alt="">`).join("") : "";
}

const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
// mesmas palavras pequenas que a busca ignora (buscador/search.py)
const STOP = new Set("a o as os e de da do das dos em na no nas nos um uma para pra com que por ao".split(" "));
const queryWords = (q) => {
  const all = fold(q).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const kept = all.filter((w) => !STOP.has(w));
  return kept.length ? kept : all;
};
function highlight(text, q) {
  // marca os trechos buscados (sem diferenciar acento e maiúscula); NFD não muda o tamanho de letras comuns
  const words = queryWords(q);
  if (!words.length) return esc(text);
  const folded = fold(text);
  if (folded.length !== text.length) return esc(text);
  const marks = new Array(text.length).fill(false);
  for (const w of words) for (let i = folded.indexOf(w); i >= 0; i = folded.indexOf(w, i + 1)) marks.fill(true, i, i + w.length);
  let out = "", on = false;
  for (let i = 0; i < text.length; i++) {
    if (marks[i] !== on) { out += marks[i] ? "<mark>" : "</mark>"; on = marks[i]; }
    out += esc(text[i]);
  }
  return out + (on ? "</mark>" : "");
}

function renderTags() {
  $("#vtags").innerHTML = current.tags.map((t) => `
    <span class="chip ${t.source}" title="${{ ai: "Gerada pela IA (" + Math.round(t.score * 100) + "%)", desc: "Tirada da descrição feita pela IA",
      face: "Pessoa reconhecida pelo rosto", user: "Adicionada por você", lr: "Veio do Lightroom" }[t.source] || ""}">
      ${esc(t.name)}<button data-t="${esc(t.name)}" title="Remover">×</button></span>`).join("")
    || `<span class="muted">Sem palavras-chave ainda.</span>`;
}
$("#vtags").addEventListener("click", async (e) => {
  const t = e.target.dataset.t;
  if (!t) return;
  current.tags = await api(`/api/file/${current.id}/tags`, { body: { remove: [t] } });
  renderTags();
});
$("#vtagForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const names = $("#vtagInput").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!names.length) return;
  current.tags = await api(`/api/file/${current.id}/tags`, { body: { add: names } });
  $("#vtagInput").value = "";
  renderTags();
});
function renderSounds() {
  const ev = current.sounds || [];
  $("#vsoundsWrap").classList.toggle("hidden", !ev.length);
  $("#vsounds").innerHTML = ev.map((e) =>
    `<button class="chip snd" data-t="${e.start}" title="força ${Math.round(e.score * 100)}%">${e.emoji} ${esc(e.label)} <span class="s">${fmtTime(e.start)}</span></button>`).join("");
}
$("#vsounds").addEventListener("click", (e) => {
  const b = e.target.closest("[data-t]");
  const video = $("#vmedia video");
  if (!b || !video) return;
  const t = Math.max(0, Number(b.dataset.t) - 1);
  if (current.light) video.src = `/api/media/${current.id}?leve=1&t=${t.toFixed(1)}`; else video.currentTime = t;
  video.play();
});

function playLight(t) {
  const v = $("#vmedia video");
  if (!v) return;
  current.light = true;
  v.src = `/api/media/${current.id}?leve=1&t=${(t || 0).toFixed(1)}`;
  v.play().catch(() => {});
  $("#vlight")?.remove();
  toast("Tocando a versão leve, convertida na hora pelo PC.");
}

function renderSpeech() {
  const segs = current.transcript || [];
  $("#vspeechWrap").classList.toggle("hidden", !segs.length);
  if (!segs.length) return;
  const q = ["auto", "texto", "falado"].includes(state.mode) ? state.q : "";
  const words = queryWords(q);
  const hits = segs.filter((s) => words.length && words.some((w) => fold(s.text).includes(w))).length;
  $("#vspeechInfo").textContent = hits ? `· ${hits} trecho${hits > 1 ? "s" : ""} com “${q}”` : "";
  $("#vspeech").innerHTML = segs.map((s) => {
    const on = words.length && words.some((w) => fold(s.text).includes(w));
    return `<div class="seg${on ? " hit" : ""}" data-t="${s.start}"><time>${fmtTime(s.start)}</time><span>${highlight(s.text, q)}</span></div>`;
  }).join("");
  const first = $("#vspeech .seg.hit");
  if (first) first.scrollIntoView({ block: "nearest" });
}
$("#vspeech").addEventListener("click", (e) => {
  const seg = e.target.closest(".seg");
  const video = $("#vmedia video");
  if (!seg || !video) return;
  if (current.light) {  // a versão leve é convertida em sequência: para pular, recomeça a conversão naquele ponto
    video.src = `/api/media/${current.id}?leve=1&t=${Number(seg.dataset.t).toFixed(1)}`;
  } else {
    video.currentTime = Number(seg.dataset.t);
  }
  video.play();
});

function renderFaces() {
  const fs = current.faces || [];
  $("#vfacesWrap").classList.toggle("hidden", !fs.length);
  $("#vfaces").innerHTML = fs.map((f) => `
    <div class="vface" data-face="${f.id}">
      <img src="/api/face/${f.id}" alt="">
      ${f.name ? `<b title="Clique para corrigir">${esc(f.name)}</b>` : `<input placeholder="Quem é?" list="peopleList">`}
    </div>`).join("");
}
$("#vfaces").addEventListener("click", (e) => {
  if (e.target.tagName !== "B") return;
  const box = e.target.closest(".vface");
  e.target.outerHTML = `<input value="${esc(e.target.textContent)}" list="peopleList">`;
  box.querySelector("input").select();
});
$("#vfaces").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" || e.target.tagName !== "INPUT") return;
  const id = Number(e.target.closest(".vface").dataset.face);
  const name = e.target.value.trim();
  if (name) await api("/api/faces/name", { body: { name, face_ids: [id] } });
  else await api("/api/faces/remove", { body: { face_ids: [id] } });
  openViewer(current.id);
});

function closeViewer() {
  $("#viewer").classList.add("hidden");
  $("#vmedia").innerHTML = "";
  refreshSide();
}
$("#vclose").addEventListener("click", closeViewer);
$("#vcloseTop").addEventListener("click", closeViewer);
// clicar no fundo escuro (fora da foto ou do vídeo) fecha o visualizador
$("#vmedia").addEventListener("click", (e) => {
  if (!e.target.closest("img, video")) closeViewer();
});
$("#vopen").addEventListener("click", () => api(`/api/open/${current.id}`, { method: "POST" }));
$("#vfolder").addEventListener("click", () => showInExplorer(current.id));
$("#vsimilar").addEventListener("click", () => {
  state.similar = current.id; state.similarName = current.name; state.q = ""; $("#q").value = "";
  closeViewer(); load();
});
document.addEventListener("keydown", (e) => {
  if ($("#viewer").classList.contains("hidden") || e.target.tagName === "INPUT") {
    if (e.key === "Escape") {
      const open = ["#indexDlg", "#peopleDlg", "#dupesDlg", "#settingsDlg", "#xmpDlg", "#xferDlg", "#healthDlg", "#albumsDlg"].filter((s) => !$(s).classList.contains("hidden"));
      if (open.length) open.forEach((s) => $(s).classList.add("hidden"));
      else if (selectMode && e.target.tagName !== "INPUT") $("#selClear").click();
    }
    return;
  }
  if (e.key === "Escape") closeViewer();
  if (e.key === "f" || e.key === "F") setFavorite([current.id], !current.favorite);
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    const i = items.findIndex((x) => x.id === current.id) + (e.key === "ArrowRight" ? 1 : -1);
    if (items[i]) openViewer(items[i].id);
  }
});

// ------------------------------------------------------------ indexação
async function loadUpdateRoots() {
  const rs = await api("/api/atualizar");
  $("#updRoots").innerHTML = rs.map((r) => `
    <label title="${esc(r.root)}"><input type="checkbox" data-serial="${r.serial}" ${r.included ? "checked" : ""}>
      <span><b>${r.letter}:</b> ${esc(r.label)}<small>${r.root.length > 3 ? esc(r.root) : "disco inteiro"}</small></span></label>`).join("");
  $("#btnUpdateAll").disabled = !rs.some((r) => r.included);
  try {
    const w = await api("/api/vigia");
    const last = w.last ? ` · última mudança às ${w.last.t}: ${[w.last.apagados && `${w.last.apagados} apagado(s)`, w.last.movidos && `${w.last.movidos} movido(s)/renomeado(s)`].filter(Boolean).join(", ")}` : "";
    $("#watchInfo").innerHTML = w.roots.length
      ? `👁 <b>Vigiando em tempo real</b> os discos marcados: arquivos apagados saem da busca na hora, renomeados e movidos são acompanhados, e novos entram sozinhos${w.waiting ? ` (${w.waiting} terminando de copiar)` : ""}${last}.`
      : "👁 Vigilância em tempo real iniciando…";
  } catch { $("#watchInfo").textContent = ""; }
}
$("#updRoots").addEventListener("change", async (e) => {
  const serial = e.target.dataset.serial;
  if (!serial) return;
  await api("/api/atualizar/disco", { body: { serial, included: e.target.checked } });
  loadUpdateRoots();
});
$("#btnUpdateAll").addEventListener("click", async () => {
  try {
    await api("/api/atualizar", { method: "POST" });
    toast("🔄 Atualizando todos os discos… acompanhe na barra da página. Dá para parar a qualquer momento.");
    pollJobs();
  } catch (err) { toast(err.message); }
});

async function openIndex() {
  $("#indexDlg").classList.remove("hidden");
  loadPending();
  loadUpdateRoots();
  const drives = await api("/api/drives");
  const known = Object.fromEntries(volumes.map((v) => [v.serial, v]));
  $("#drives").innerHTML = drives.map((d) => {
    const k = known[d.serial];
    const size = d.total ? (d.total / 1e9).toFixed(0) + " GB" : "";
    return `<button class="drive" data-p="${d.letter}:\\"><b>${d.letter}: ${esc(d.label)}</b>
      <small>${size}${k ? " · " + (k.files || 0).toLocaleString("pt-BR") + " arquivos" : " · nunca indexado"}</small></button>`;
  }).join("");
}
window.openIndex = openIndex;
$("#btnIndex").addEventListener("click", openIndex);
$("#indexDlg").addEventListener("click", (e) => { if (e.target.dataset.close !== undefined || e.target.id === "indexDlg") $("#indexDlg").classList.add("hidden"); });
$("#drives").addEventListener("click", (e) => {
  const b = e.target.closest(".drive");
  if (b && confirm(`Indexar o disco ${b.dataset.p} inteiro?`)) startScan(b.dataset.p);
});
$("#pathForm").addEventListener("submit", (e) => { e.preventDefault(); if ($("#pathInput").value.trim()) startScan($("#pathInput").value); });
async function loadPending() {
  const p = await api("/api/pendentes");
  const row = (label, n, note = "") =>
    `<div class="pend-row${n ? "" : " ok"}"><span>${label}</span><b>${n ? nfmt(n) : "✓ em dia"}</b>${note ? `<small class="muted">${note}</small>` : ""}</div>`;
  $("#pendList").innerHTML =
    row("Palavras-chave e estrelas do Lightroom", p.lightroom) +
    row("Palavras-chave da IA", p.ia) +
    row("Fotos ruins (para revisar)", p.qualidade) +
    row("Descrição em português", p.descricao) +
    row("Rostos", p.rostos) +
    row("Texto escrito nas fotos", p.ocr) +
    row("Fala dos vídeos", p.fala, p.fala_offline ? `+ ${nfmt(p.fala_offline)} em discos desconectados (conecte para transcrever)` : "") +
    row("Sons dos vídeos (aplausos, fogos…)", p.som, p.som_offline ? `+ ${nfmt(p.som_offline)} em discos desconectados` : "") +
    (p.miniaturas ? row("Ainda sem miniatura", p.miniaturas, "esses precisam de “Indexar” no disco onde estão") : "");
  const total = p.lightroom + p.ia + p.qualidade + p.descricao + p.rostos + p.ocr + p.fala + p.som;
  $("#btnPending").disabled = !total;
  $("#btnPending").textContent = total ? "Processar tudo que está pendente" : "Nada pendente";
}
$("#btnPending").addEventListener("click", async () => {
  await api("/api/pendentes", { method: "POST" });
  toast("Processando o que falta: palavras-chave, descrição, rostos, texto, fala e sons. Dá para parar a qualquer momento.");
  pollJobs();
});
$("#btnRedo").addEventListener("click", () => { if (confirm("Refazer as palavras-chave da IA em todos os arquivos? (as suas são mantidas)")) api("/api/ai?redo=true", { method: "POST" }).then(pollJobs); });
async function stopJob() {
  if (!confirm("Parar a tarefa em andamento? O que já foi feito fica salvo; indexando de novo, continua de onde parou.")) return;
  await api("/api/cancel", { method: "POST" });
  pollJobs();
}
$("#btnCancel").addEventListener("click", stopJob);
document.addEventListener("click", (e) => { if (e.target.closest("[data-stop]")) stopJob(); });

async function startScan(path) {
  try {
    await api("/api/scan", { body: { path } });
    $("#pathInput").value = "";
    pollJobs();
  } catch (err) { alert(err.message); }
}

// as três frentes que rodam juntas (imagens, áudio, texto) enquanto os discos são lidos
const LANE_NAMES = { imagem: "Imagens", audio: "Áudio", texto: "Texto" };
const STAGE_NAMES = { lightroom: "Lightroom", ia: "palavras-chave", qualidade: "fotos ruins", descricao: "descrição",
  rostos: "rostos", ocr: "texto nas fotos", fala: "fala", som: "sons", pronto: "em dia" };
function lanesHtml(lanes) {
  if (!lanes) return "";
  const n = (v) => (v || 0).toLocaleString("pt-BR");
  const parts = Object.entries(LANE_NAMES).filter(([k]) => lanes[k]).map(([k, label]) => {
    const l = lanes[k];
    const busy = l.stage !== "pronto" && l.total;
    const txt = busy ? `${STAGE_NAMES[l.stage] || l.stage} ${n(l.done)}/${n(l.total)}` + (l.per_hour ? ` · ${n(l.per_hour)}/h` : "")
      : (l.stage === "pronto" ? "em dia" : "aguardando arquivos");
    return `<span class="lane${busy ? " busy" : ""}"><b>${label}</b> ${esc(txt)}</span>`;
  });
  return parts.length ? `<div class="lanes">${parts.join("")}</div>` : "";
}

let pollTimer, wasRunning = false;
async function pollJobs() {
  clearTimeout(pollTimer);
  const s = await api("/api/jobs").catch(() => null);
  const bar = $("#jobBar");
  const c = s?.current;
  if (c) {
    const p = c.progress || {};
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    const what = c.kind === "scan" ? `Indexando ${esc(c.path || "")}` : c.kind === "rostos" ? "Rostos"
      : c.kind === "ocr" ? "Lendo texto nas fotos" : c.kind === "fala" ? "Transcrevendo vídeos"
      : c.kind === "duplicados" ? "Procurando duplicados" : c.kind === "xmp" ? "Gravando palavras-chave"
      : c.kind === "arquivos" ? "Arquivos novos" : c.kind === "etapas" || c.kind === "pendentes" ? "Processando" : c.kind === "atualizar" ? "Atualizando os discos" : c.kind === "leitura" ? "Teste de leitura" : c.kind === "qualidade" ? "Fotos ruins" : c.kind === "descricao" ? "Descrevendo" : c.kind === "lightroom" ? "Lightroom" : "IA";
    const detail = p.total ? `${p.done.toLocaleString("pt-BR")} de ${p.total.toLocaleString("pt-BR")}` : (p.found ? `${p.found.toLocaleString("pt-BR")} encontrados` : "");
    const rate = (p.per_hour ? ` · ${p.per_hour.toLocaleString("pt-BR")}/hora` : "")
      + (p.eta_min ? ` · faltam ~${p.eta_min >= 60 ? Math.round(p.eta_min / 60) + " h" : p.eta_min + " min"}` : "");
    const queued = s.queued.length ? ` · ${s.queued.length} na fila` : "";
    const stopBtn = c.stopping
      ? `<button class="ghost danger" disabled>Parando…</button>`
      : `<button class="ghost danger pc-only" data-stop title="Interrompe a tarefa. Rodando de novo, continua de onde parou.">■ Parar</button>`;
    bar.innerHTML = `<b>${what}</b><span>${esc(p.phase || "")} ${detail}${rate}${queued}</span><div class="prog"><i style="width:${pct}%"></i></div>${c.lanes ? `<span class="jtoggle" title="Mostrar/esconder detalhes">▾</span>` : ""}${stopBtn}${lanesHtml(c.lanes)}`;
    bar.classList.remove("hidden");
    $("#jobDetail").innerHTML = bar.innerHTML;
    wasRunning = true;
    pollTimer = setTimeout(pollJobs, 1500);
  } else {
    bar.classList.add("hidden");
    const last = s?.history?.at(-1);
    $("#jobDetail").textContent = last ? (!last.ok ? `Erro: ${last.error}` : last.stopped ? `Tarefa parada: ${last.path || last.kind}` : `Última tarefa concluída: ${last.path || last.kind}`) : "";
    if (wasRunning) {
      wasRunning = false; refreshSide(); load();
      if (last?.kind === "xmp" && last.ok) toast(xmpSummary(last.result));
      if (!$("#dupesDlg").classList.contains("hidden")) loadDupes();
      if (!$("#indexDlg").classList.contains("hidden")) loadPending();
    }
    pollTimer = setTimeout(pollJobs, 8000);
  }
}

// ------------------------------------------------------------ pessoas
let pd = null;  // {person_id, name} ou {cluster_id}
const pdSel = new Set();

async function openPeople() {
  $("#peopleDlg").classList.remove("hidden");
  $("#peopleMain").classList.remove("hidden");
  $("#peopleDetail").classList.add("hidden");
  const data = await api("/api/people");
  $("#peopleList").innerHTML = data.people.map((p) => `<option value="${esc(p.name)}">`).join("");
  $("#peopleNamed").innerHTML = data.people.map((p) => `
    <div class="pcard${combine.has(p.id) ? " picked" : ""}" data-person="${p.id}" data-name="${esc(p.name)}">
      <button class="ppick" data-ppick="${p.id}" title="Marcar para combinar" aria-label="Marcar ${esc(p.name)} para combinar" aria-pressed="${combine.has(p.id)}">✓</button>
      <img src="/api/face/${p.cover}" alt=""><b>${esc(p.name)}</b><small>${p.files} arquivo${p.files > 1 ? "s" : ""}</small>
    </div>`).join("") || `<div class="muted">Ninguém com nome ainda.</div>`;
  $("#peopleGroups").innerHTML = data.groups.map((g) => `
    <div class="pcard" data-cluster="${g.cluster_id}">
      <img src="/api/face/${g.cover}" alt=""><small>${g.files} arquivos</small>
      <input placeholder="Quem é?" list="peopleList">
    </div>`).join("") || `<div class="muted">Nenhum grupo de rostos. Indexe pastas com fotos de pessoas.</div>`;
}
$("#btnPeople").addEventListener("click", openPeople);
$("#peopleDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "peopleDlg") { $("#peopleDlg").classList.add("hidden"); refreshSide(); }
});
$("#btnFaces").addEventListener("click", () => api("/api/rostos", { method: "POST" }).then(pollJobs));

function pcardClick(e) {
  if (e.target.tagName === "INPUT") return;
  const pick = e.target.closest("[data-ppick]");
  if (pick) { togglePick(Number(pick.dataset.ppick), pick.closest(".pcard").dataset.name); return; }
  const c = e.target.closest(".pcard");
  if (!c) return;
  openPersonDetail(c.dataset.person ? { person_id: Number(c.dataset.person), name: c.dataset.name } : { cluster_id: Number(c.dataset.cluster) });
}
$("#peopleNamed").addEventListener("click", pcardClick);
$("#peopleGroups").addEventListener("click", pcardClick);
$("#peopleGroups").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" || !e.target.value.trim()) return;
  await api("/api/faces/name", { body: { name: e.target.value, cluster_id: Number(e.target.closest(".pcard").dataset.cluster) } });
  openPeople();
});

async function openPersonDetail(target) {
  pd = target;
  pdSel.clear();
  $("#peopleMain").classList.add("hidden");
  $("#peopleDetail").classList.remove("hidden");
  $("#pdName").value = pd.name || "";
  $("#pdName").placeholder = pd.name ? "Nome da pessoa" : "Quem é? Digite o nome deste grupo";
  $("#pdShow").classList.toggle("hidden", !pd.name);
  $("#pdNotHer").classList.toggle("hidden", !pd.name);
  const q = pd.person_id ? `person=${pd.person_id}` : `cluster=${pd.cluster_id}`;
  const fs = await api(`/api/faces?${q}`);
  $("#pdFaces").innerHTML = fs.map((f) => `
    <div class="fcrop" data-face="${f.id}" data-file="${f.file_id}" title="${f.manual ? "Confirmado por você" : "Reconhecido automaticamente"}">
      <img src="/api/face/${f.id}" alt=""><span class="open" data-file="${f.file_id}">abrir</span>
    </div>`).join("");
}
$("#pdBack").addEventListener("click", openPeople);
$("#pdFaces").addEventListener("click", (e) => {
  if (e.target.classList.contains("open")) {
    $("#peopleDlg").classList.add("hidden");
    openViewer(Number(e.target.dataset.file));
    return;
  }
  const c = e.target.closest(".fcrop");
  if (!c) return;
  const id = Number(c.dataset.face);
  pdSel.has(id) ? pdSel.delete(id) : pdSel.add(id);
  c.classList.toggle("sel", pdSel.has(id));
});
$("#pdNameForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#pdName").value.trim();
  if (!name) return;
  const body = pdSel.size ? { name, face_ids: [...pdSel] } : { name, ...(pd.person_id ? { person_id: pd.person_id } : { cluster_id: pd.cluster_id }) };
  const r = await api("/api/faces/name", { body });
  if (!pdSel.size) openPersonDetail({ person_id: r.person_id, name });
  else openPersonDetail(pd);
});
$("#pdNameSel").addEventListener("click", async () => {
  if (!pdSel.size) return alert("Selecione os rostos primeiro.");
  const name = prompt("Nome para os rostos selecionados:");
  if (!name) return;
  await api("/api/faces/name", { body: { name, face_ids: [...pdSel] } });
  openPersonDetail(pd);
});
$("#pdNotHer").addEventListener("click", async () => {
  if (!pdSel.size) return alert("Selecione os rostos que não são dessa pessoa.");
  await api("/api/faces/remove", { body: { face_ids: [...pdSel] } });
  openPersonDetail(pd);
});
$("#pdIgnore").addEventListener("click", async () => {
  const body = pdSel.size ? { face_ids: [...pdSel] } : pd.cluster_id != null ? { cluster_id: pd.cluster_id } : null;
  if (!body) return alert("Selecione os rostos que quer ignorar.");
  if (!confirm(pdSel.size ? "Ignorar os rostos selecionados?" : "Ignorar este grupo inteiro (desconhecidos)?")) return;
  await api("/api/faces/ignore", { body });
  pdSel.size ? openPersonDetail(pd) : openPeople();
});
$("#pdShow").addEventListener("click", () => {
  state.people = [{ id: pd.person_id, name: pd.name }]; state.q = ""; $("#q").value = ""; state.similar = null;
  $("#peopleDlg").classList.add("hidden");
  refreshSide(); load();
});

// ------------------------------------------------------------ para revisar (fotos ruins)
const REVIEW_REASON = { borrada: "borrada", escura: "escura", clara: "estourada", repetida: "repetida" };

async function refreshReview() {
  const r = await api("/api/revisar").catch(() => null);
  if (!r) return;
  $("#reviewCount").textContent = nfmt(r.total);
  $("#reviewEntry").classList.toggle("on", !!state.review);
  $("#reviewHead").classList.toggle("hidden", !state.review);
  const parts = Object.entries(r.por_motivo).map(([k, n]) => `${nfmt(n)} ${REVIEW_REASON[k] || k}${n > 1 && k !== "clara" ? "s" : ""}`);
  $("#reviewInfo").textContent = r.total ? parts.join(" · ") : "Nada para revisar agora. Fotos novas entram aqui sozinhas.";
}
$("#reviewEntry").addEventListener("click", () => {
  state.review = !state.review;
  if (state.review) { state.q = ""; $("#q").value = ""; state.photo = null; state.album = null; }
  refreshReview(); syncSelection(); load();
});
$("#bulkKeep").addEventListener("click", async () => {
  const ids = [...selected];
  await api("/api/revisar/manter", { body: { ids } });
  toast(`✓ ${ids.length} mantida${ids.length === 1 ? "" : "s"} — não voltam para a revisão`);
  selected.clear(); syncSelection(); refreshReview(); load();
});
$("#bulkReviewTrash").addEventListener("click", async () => {
  const ids = [...selected];
  if (!confirm(`Mandar ${ids.length} foto${ids.length === 1 ? "" : "s"} para a lixeira do BuscadorFAST?\n\nElas saem das pastas, mas dá para restaurar em Duplicados → Lixeira. O espaço só é liberado ao esvaziar a lixeira.`)) return;
  const r = await api("/api/revisar/lixeira", { body: { ids } });
  toast(`🗑 ${r.moved} na lixeira (${fmtBytes(r.bytes)})${r.failed ? ` · ${r.failed} não puderam ser movidas (disco desconectado?)` : ""}`);
  selected.clear(); syncSelection(); refreshReview(); refreshSide(); load();
});

// ------------------------------------------------------------ álbuns automáticos
$("#albumsEntry").addEventListener("click", async () => {
  $("#albumsDlg").classList.remove("hidden");
  $("#albumsGrid").innerHTML = `<div class="muted">Montando os álbuns…</div>`;
  const p = new URLSearchParams({ kind: state.kind, only_online: state.onlyOnline });
  if (state.volume) p.set("volume", state.volume);
  const al = await api("/api/albuns?" + p);
  let lastMonth = "";
  $("#albumsGrid").innerHTML = al.map((a, i) => {
    const d = new Date(a.day + "T12:00");
    const month = d.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
    const head = month !== lastMonth ? `<div class="amonth">${month}</div>` : "";
    lastMonth = month;
    const counts = [a.photos && `${a.photos} foto${a.photos > 1 ? "s" : ""}`, a.videos && `${a.videos} vídeo${a.videos > 1 ? "s" : ""}`].filter(Boolean).join(", ");
    return `${head}<div class="acard" data-i="${i}">
      <img loading="lazy" src="/api/thumb/${a.cover}" alt="">
      <div class="t"><b>${a.gps ? "📍" : "📁"} ${esc(a.title)}</b>
      <small>${d.toLocaleDateString("pt-BR", { weekday: "short", day: "numeric", month: "short" })} · ${a.start}–${a.end}</small>
      <small>${counts}</small></div></div>`;
  }).join("") || `<div class="muted">Nenhum álbum ainda (é preciso pelo menos 4 fotos ou vídeos do mesmo dia e lugar).</div>`;
  $("#albumsGrid").onclick = (e) => {
    const c = e.target.closest(".acard");
    if (!c) return;
    const a = al[Number(c.dataset.i)];
    state.album = { key: a.key, title: `${a.title} · ${new Date(a.day + "T12:00").toLocaleDateString("pt-BR")}` };
    state.q = ""; $("#q").value = ""; state.photo = null; state.similar = null;
    $("#albumsDlg").classList.add("hidden");
    load();
  };
});
$("#albumsDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "albumsDlg") $("#albumsDlg").classList.add("hidden");
});

// ------------------------------------------------------------ saúde dos discos
const HEALTH_LABEL = { ok: "OK", atencao: "Atenção", problema: "Problema" };  // a bolinha colorida vem do CSS

function healthCard(d) {
  const kind = d.bus === "USB" ? `${d.media} externo (USB)` : d.bus === "NVMe" ? "SSD NVMe" : `${d.media} ${d.bus}`;
  const vols = (d.volumes || []).map((v) => {
    const used = v.size ? 100 * (1 - v.free / v.size) : 0;
    return `<dt>${esc(v.letter)}:</dt><dd>${fmtBytes(v.free)} livres de ${fmtBytes(v.size)}<div class="bar"><i style="width:${used.toFixed(0)}%"></i></div></dd>`;
  }).join("");
  const n = (v) => (typeof v === "number" && v > 0 ? v : null);
  const rows = [
    n(d.temp) && ["Temperatura", `${d.temp} °C`],
    n(d.hours) && ["Horas ligado", `${nfmt(d.hours)} h (${(d.hours / 24 / 365).toFixed(1).replace(".", ",")} anos)`],
    n(d.wear) && ["Desgaste", `${d.wear}%`],
    d.readCorr != null && ["Erros de leitura", `${d.readCorr || 0} corrigido(s)${d.readUncorr ? `, ${d.readUncorr} não corrigido(s)` : ""}`],
  ].filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  return `<div class="hcard ${d.level}">
    <h4><span>${esc((d.letters || []).map((l) => l + ":").join(" ") || "sem letra")} ${esc(d.model)}</span><span>${HEALTH_LABEL[d.level]}</span></h4>
    <div class="sub">${esc(kind)} · ${fmtBytes(d.size)} · Windows: ${d.health === "Healthy" ? "saudável" : esc(d.health)}${d.smart ? "" : " · sem dados internos (caixa USB)"}</div>
    <dl>${vols}${rows}</dl>
    ${d.reasons.length ? `<ul>${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

async function loadHealth(force = false) {
  const r = await api(`/api/saude${force ? "?atualizar=true" : ""}`);
  $("#healthBadge").textContent = r.worst === "ok" ? "" : r.worst === "atencao" ? "⚠" : "❌";
  if (!$("#healthDlg").classList.contains("hidden")) {
    $("#healthList").innerHTML = r.disks.map(healthCard).join("");
    $("#healthWhen").textContent = `verificado às ${new Date(r.checked).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  }
  return r;
}
$("#btnHealth").addEventListener("click", () => {
  $("#healthDlg").classList.remove("hidden");
  $("#healthList").innerHTML = `<div class="muted">Lendo os discos…</div>`;
  loadHealth().catch((e) => { $("#healthList").innerHTML = `<div class="muted">${esc(e.message)}</div>`; });
});
$("#healthRefresh").addEventListener("click", () => loadHealth(true));

async function loadReadTest() {
  const r = await api("/api/leitura");
  $("#readList").innerHTML = r.volumes.map((v) => {
    const pct = v.bytes ? (100 * v.tested_bytes) / v.bytes : 0;
    return `<div class="readrow${v.errors ? " bad" : ""}"><b>${esc(v.label)}</b>${v.online ? "" : " · desconectado"} —
      ${nfmt(v.tested)} de ${nfmt(v.files)} arquivos lidos (${pct.toFixed(0)}%)${v.errors ? ` · <b>${v.errors} com problema</b>` : " · nenhum problema"}${v.last ? ` · último teste ${new Date(v.last).toLocaleDateString("pt-BR")}` : ""}
      <div class="bar"><i style="width:${pct.toFixed(1)}%"></i></div></div>`;
  }).join("");
  $("#readErrors").innerHTML = r.errors.length
    ? `<h4 class="muted small">Arquivos com problema</h4>` + r.errors.map((e) =>
      `<div class="readerr">${esc(e.label)} ${esc(e.relpath)} — ${esc(e.read_error)}</div>`).join("") : "";
}
$("#readNow").addEventListener("click", async () => {
  await api("/api/leitura", { body: { horas: 2 } });
  toast("Teste de leitura na fila (2 horas). Ele começa quando a tarefa atual terminar.");
  pollJobs();
});
$("#btnHealth").addEventListener("click", () => loadReadTest().catch(() => {}));
$("#healthDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "healthDlg") $("#healthDlg").classList.add("hidden");
});

// ------------------------------------------------------------ mapa
const mapState = { open: false, map: null, layer: null, ready: null };

function loadScript(src) {
  return new Promise((ok, fail) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
}
function loadCss(href) { const l = document.createElement("link"); l.rel = "stylesheet"; l.href = href; document.head.appendChild(l); }
function leaflet() {
  // só baixa a biblioteca do mapa quando você abre o mapa (precisa de internet para os mapas)
  mapState.ready ||= (async () => {
    const cdn = "https://cdnjs.cloudflare.com/ajax/libs";
    loadCss(`${cdn}/leaflet/1.9.4/leaflet.min.css`);
    loadCss(`${cdn}/leaflet.markercluster/1.5.3/MarkerCluster.min.css`);
    loadCss(`${cdn}/leaflet.markercluster/1.5.3/MarkerCluster.Default.min.css`);
    await loadScript(`${cdn}/leaflet/1.9.4/leaflet.min.js`);
    await loadScript(`${cdn}/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js`);
  })();
  return mapState.ready;
}

$("#btnMap").addEventListener("click", async () => {
  mapState.open = !mapState.open;
  $("#mapBox").classList.toggle("hidden", !mapState.open);
  $("#btnMap").classList.toggle("on", mapState.open);
  if (!mapState.open) return;
  try { await leaflet(); } catch { $("#mapInfo").textContent = "Não consegui carregar o mapa (precisa de internet)."; return; }
  if (!mapState.map) {
    mapState.map = L.map("map", { worldCopyJump: true }).setView([-8.5, -40.7], 8);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(mapState.map);
  }
  // o mapa precisa saber o próprio tamanho na tela antes de enquadrar os pontos
  await new Promise((r) => setTimeout(r, 80));
  mapState.map.invalidateSize();
  loadMap(true);
});

let mapSeq = 0;
async function loadMap(fit = false) {
  if (!mapState.open || !mapState.map) return;
  const seq = ++mapSeq;  // se outra carga começar no meio, esta desiste (evita pontos sumindo)
  const p = new URLSearchParams({ kind: state.kind, tag: state.tags.join(","), camera: state.camera,
    date_from: state.dateFrom, date_to: state.dateTo, only_online: state.onlyOnline, favorite: !!state.favorite });
  peopleParams(p);
  if (state.volume) p.set("volume", state.volume);
  if (state.collection) p.set("collection", state.collection);
  const pts = await api("/api/mapa?" + p);
  if (seq !== mapSeq) return;
  if (mapState.layer) mapState.map.removeLayer(mapState.layer);
  // enquadra primeiro, sem animação: os grupos de pontos são calculados para o zoom final
  if (fit && pts.length) mapState.map.fitBounds(L.latLngBounds(pts.map(([, a, b]) => [a, b])), { padding: [20, 20], maxZoom: 14, animate: false });
  mapState.layer = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 50 });
  for (const [id, lat, lon, video] of pts) {
    const m = L.marker([lat, lon], { icon: L.divIcon({ className: "", html: `<div class="map-dot${video ? " video" : ""}"></div>`, iconSize: [12, 12] }) });
    m.bindPopup(`<div class="map-pop"><img src="/api/thumb/${id}" alt=""><button data-open="${id}">Abrir</button></div>`);
    mapState.layer.addLayer(m);
  }
  mapState.map.addLayer(mapState.layer);
  $("#mapInfo").textContent = pts.length
    ? `${nfmt(pts.length)} com localização · 🔵 foto · 🟠 vídeo · aproxime e clique num ponto`
    : "Nenhum arquivo com localização nos filtros atuais (só fotos e vídeos com GPS: celular, drone…).";
}
$("#map").addEventListener("click", (e) => { const id = e.target.dataset?.open; if (id) openViewer(Number(id)); });
$("#mapArea").addEventListener("click", () => {
  const b = mapState.map.getBounds();
  state.area = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].map((x) => x.toFixed(5)).join(",");
  load();
});

// ------------------------------------------------------------ busca por voz
// O celular só libera o microfone em conexão segura (https): por isso o QR code leva ao endereço seguro.
const voice = { rec: null, chunks: [], timer: null };

$("#micBtn").addEventListener("click", async () => {
  if (voice.rec) return voice.rec.stop();  // segundo toque: termina e busca
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    return toast("Para falar, abra o BuscadorFAST pelo endereço seguro (no PC: ⚙ → Acesso pelo celular → QR code).");
  }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { return toast("O microfone não foi liberado. Permita o microfone para este site e tente de novo."); }
  const type = ["audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
  voice.rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  voice.chunks = [];
  voice.rec.ondataavailable = (e) => e.data.size && voice.chunks.push(e.data);
  voice.rec.onstop = async () => {
    clearTimeout(voice.timer);
    stream.getTracks().forEach((t) => t.stop());
    $("#micBtn").classList.remove("rec"); $("#micBtn").textContent = "🎤";
    const blob = new Blob(voice.chunks, { type: voice.rec.mimeType || type });
    voice.rec = null;
    if (blob.size < 2000) return toast("Não ouvi nada.");
    toast("Entendendo o que você falou…");
    const r = await fetch("/api/voz", { method: "PUT", body: blob, headers: { "Content-Type": blob.type || "audio/webm" } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return toast(data.detail || "Não consegui entender.");
    $("#q").value = data.texto; state.q = data.texto; state.similar = null; state.photo = null;
    toast(`🎤 “${data.texto}”`);
    load();
  };
  voice.rec.start();
  $("#micBtn").classList.add("rec"); $("#micBtn").textContent = "■";
  toast("Ouvindo… fale o que procura e toque em ■ (para sozinho em 8 s).");
  voice.timer = setTimeout(() => voice.rec?.stop(), 8000);
});

// ------------------------------------------------------------ buscar pessoa pelo rosto (foto enviada)
async function searchByPhoto(file) {
  if (!file || !file.type.startsWith("image/")) return;
  toast("Reconhecendo o rosto…");
  const r = await fetch("/api/buscar-por-foto", { method: "PUT", body: file });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return toast(data.detail || "Não consegui ler essa imagem.");
  const { foto, faces, found } = data;
  toast(found
    ? `🙂 Pessoa encontrada em ${nfmt(found)} arquivo${found === 1 ? "" : "s"}${faces > 1 ? ` (a foto tinha ${faces} rostos: usei o maior)` : ""}`
    : "Não achei essa pessoa em nenhum arquivo do catálogo.");
  state.photo = { token: foto, preview: URL.createObjectURL(file) };
  state.q = ""; $("#q").value = ""; state.similar = null;
  load();
}
$("#photoInput").addEventListener("change", (e) => { searchByPhoto(e.target.files[0]); e.target.value = ""; });
// arrastar uma imagem para qualquer lugar da tela (do Explorer, do WhatsApp Web…)
let dragDepth = 0;
const isFileDrag = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
document.addEventListener("dragenter", (e) => { if (!isFileDrag(e) || !$("#xferDlg").classList.contains("hidden")) return; dragDepth++; $("#dropHint").classList.remove("hidden"); });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#dropHint").classList.add("hidden"); } });
document.addEventListener("dragover", (e) => { if (isFileDrag(e)) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault(); dragDepth = 0; $("#dropHint").classList.add("hidden");
  if ($("#xferDlg").classList.contains("hidden")) searchByPhoto(e.dataTransfer.files[0]);
});
// colar uma imagem (Ctrl+V) — ex.: um print
document.addEventListener("paste", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) searchByPhoto(item.getAsFile());
});

// ------------------------------------------------------------ linha do tempo
const tl = { open: false, year: "", month: "", day: "" };
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const nfmt = (n) => n.toLocaleString("pt-BR");

$("#btnTimeline").addEventListener("click", () => {
  tl.open = !tl.open;
  $("#timeline").classList.toggle("hidden", !tl.open);
  $("#btnTimeline").classList.toggle("on", tl.open);
  if (tl.open) loadTimeline();
  render();  // põe ou tira os cabeçalhos de data entre os resultados
});

function setDates(from, to) {
  state.dateFrom = from; state.dateTo = to;
  $("#dateFrom").value = from; $("#dateTo").value = to;
  load();
}

function periodLabel(level, k) {
  if (level === "ano") return k;
  const [y, m, d] = k.split("-");
  if (level === "mes") return `${MESES[Number(m) - 1]} de ${y}`;
  return new Date(`${y}-${m}-${d}T12:00`).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

async function loadTimeline() {
  if (!tl.open) return;
  const p = new URLSearchParams({ year: tl.year, month: tl.month, kind: state.kind, tag: state.tags.join(","),
    camera: state.camera, only_online: state.onlyOnline, favorite: !!state.favorite });
  peopleParams(p);
  if (state.volume) p.set("volume", state.volume);
  if (state.collection) p.set("collection", state.collection);
  const r = await api("/api/linha-do-tempo?" + p);
  const got = Object.fromEntries(r.buckets.map((b) => [b.k, b]));

  // todos os períodos do intervalo, inclusive os vazios (sem buracos na linha do tempo)
  let keys = [];
  if (r.level === "ano") {
    const ys = r.buckets.map((b) => Number(b.k)).filter((y) => y > 1980 && y < 2100);
    if (ys.length) for (let y = Math.min(...ys); y <= Math.max(...ys); y++) keys.push(String(y));
    keys = keys.concat(r.buckets.map((b) => b.k).filter((k) => !keys.includes(k)));  // datas estranhas aparecem também
  } else if (r.level === "mes") {
    keys = Array.from({ length: 12 }, (_, i) => `${tl.year}-${String(i + 1).padStart(2, "0")}`);
  } else {
    const days = new Date(Number(tl.year), Number(tl.month), 0).getDate();
    keys = Array.from({ length: days }, (_, i) => `${tl.year}-${tl.month}-${String(i + 1).padStart(2, "0")}`);
  }
  const data = keys.map((k) => got[k] || { k, n: 0, videos: 0 });
  const max = Math.max(1, ...data.map((b) => b.n));
  const sel = r.level === "ano" ? tl.year : r.level === "mes" ? (tl.month && `${tl.year}-${tl.month}`) : (tl.day && `${tl.year}-${tl.month}-${tl.day}`);
  const peak = data.reduce((a, b) => (b.n > a.n ? b : a), data[0] || { n: 0 });

  $("#tlChart").innerHTML = data.map((b) => {
    const h = (b.n / max) * 100;
    const showV = b.n && (b.k === peak.k || b.k === sel);  // número só no maior e no escolhido
    return `<button class="tl-bar${b.n ? " has" : ""}${b.k === sel ? " on" : ""}" role="listitem" data-k="${b.k}" data-n="${b.n}" data-v="${b.videos || 0}"
      ${b.n ? "" : "disabled"} aria-label="${periodLabel(r.level, b.k)}: ${nfmt(b.n)} arquivos">
      ${showV ? `<span class="v" style="bottom:calc(${h}% + 2px)">${nfmt(b.n)}</span>` : ""}<i style="height:${h}%"></i></button>`;
  }).join("");
  const short = (k) => r.level === "ano" ? k : r.level === "mes" ? MESES[Number(k.slice(5, 7)) - 1].slice(0, 3) : String(Number(k.slice(8)));
  document.querySelector(".tl-axis")?.remove();
  $("#tlChart").insertAdjacentHTML("afterend", `<div class="tl-axis">${data.map((b) => `<span>${short(b.k)}</span>`).join("")}</div>`);

  const crumbs = [`<button data-go="root">Todas as datas</button>`];
  if (tl.year) crumbs.push(`<span class="sep">›</span>`, tl.month ? `<button data-go="year">${tl.year}</button>` : `<b>${tl.year}</b>`);
  if (tl.month) crumbs.push(`<span class="sep">›</span>`, tl.day ? `<button data-go="month">${MESES[Number(tl.month) - 1]}</button>` : `<b>${MESES[Number(tl.month) - 1]}</b>`);
  if (tl.day) crumbs.push(`<span class="sep">›</span>`, `<b>dia ${Number(tl.day)}</b>`);
  $("#tlCrumbs").innerHTML = crumbs.join(" ");
  const total = data.reduce((a, b) => a + b.n, 0);
  $("#tlInfo").textContent = `${nfmt(total)} com data` + (r.undated ? ` · ${nfmt(r.undated)} ainda sem data (aguardando indexação)` : "")
    + (r.level === "dia" ? " · clique num dia para ver só ele" : " · clique numa barra para abrir");
}

$("#tlChart").addEventListener("click", (e) => {
  const b = e.target.closest(".tl-bar");
  if (!b || b.disabled) return;
  const k = b.dataset.k;
  if (!tl.year) {
    tl.year = k; setDates(`${k}-01-01`, `${k}-12-31`);
  } else if (!tl.month) {
    tl.month = k.slice(5, 7);
    const last = new Date(Number(tl.year), Number(tl.month), 0).getDate();
    setDates(`${k}-01`, `${k}-${last}`);
  } else {
    const d = k.slice(8, 10);
    if (tl.day === d) {  // clicar de novo no mesmo dia volta para o mês inteiro
      tl.day = "";
      const last = new Date(Number(tl.year), Number(tl.month), 0).getDate();
      setDates(`${tl.year}-${tl.month}-01`, `${tl.year}-${tl.month}-${last}`);
    } else {
      tl.day = d; setDates(k, k);
    }
  }
});
$("#tlCrumbs").addEventListener("click", (e) => {
  const go = e.target.dataset.go;
  if (!go) return;
  if (go === "root") { tl.year = tl.month = tl.day = ""; setDates("", ""); }
  else if (go === "year") { tl.month = tl.day = ""; setDates(`${tl.year}-01-01`, `${tl.year}-12-31`); }
  else if (go === "month") {
    tl.day = "";
    const last = new Date(Number(tl.year), Number(tl.month), 0).getDate();
    setDates(`${tl.year}-${tl.month}-01`, `${tl.year}-${tl.month}-${last}`);
  }
});

// dica ao passar o mouse (ou focar com o teclado)
function tlTip(e) {
  const b = e.target.closest?.(".tl-bar");
  const tip = $("#tlTip");
  if (!b || !Number(b.dataset.n)) { tip.classList.add("hidden"); return; }
  const level = !tl.year ? "ano" : !tl.month ? "mes" : "dia";
  const v = Number(b.dataset.v);
  tip.innerHTML = `<b>${periodLabel(level, b.dataset.k)}</b> · ${nfmt(Number(b.dataset.n))} arquivo${b.dataset.n === "1" ? "" : "s"}${v ? ` (${nfmt(v)} vídeo${v > 1 ? "s" : ""})` : ""}`;
  const box = $("#timeline").getBoundingClientRect(), r = b.getBoundingClientRect(), bar = b.querySelector("i").getBoundingClientRect();
  const half = tip.offsetWidth / 2 || 80;
  const x = Math.min(Math.max(r.left + r.width / 2 - box.left, half), box.width - half);
  tip.style.left = x + "px";
  tip.style.top = (bar.top - box.top - 6) + "px";
  tip.classList.remove("hidden");
}
$("#tlChart").addEventListener("mousemove", tlTip);
$("#tlChart").addEventListener("focusin", tlTip);
$("#tlChart").addEventListener("mouseleave", () => $("#tlTip").classList.add("hidden"));
$("#tlChart").addEventListener("focusout", () => $("#tlTip").classList.add("hidden"));

// cabeçalho de data entre os resultados quando estão em ordem de data
function dateOrdered() {
  if (state.sort === "data_desc" || state.sort === "data_asc") return true;
  return tl.open && state.sort === "relevancia" && !state.q.trim() && !state.similar && !state.collection;
}
function dayOf(it) { return (it.taken_at || "").slice(0, 10); }
function withDayHeads(list, prevDay) {
  let out = "", last = prevDay;
  for (const it of list) {
    const d = dayOf(it);
    if (d && d !== last) {
      out += `<div class="dayhead">${periodLabel("dia", d)}</div>`;
      last = d;
    }
    out += tileHtml(it);
  }
  return out;
}

// ------------------------------------------------------------ favoritos e coleções
let colls = [];

async function refreshColls() {
  const r = await api("/api/colecoes");
  colls = r.collections;
  $("#favCount").textContent = r.favorites.toLocaleString("pt-BR");
  $("#favEntry").classList.toggle("on", !!state.favorite);
  $("#collList").innerHTML = colls.map((c) => `
    <div class="vol coll${state.collection === c.id ? " on" : ""}" data-coll="${c.id}">
      <span class="ico">📁</span><span class="name">${esc(c.name)}</span><small>${c.n}</small>
    </div>`).join("");
  const opts = colls.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  $("#vcollAdd").innerHTML = `<option value="">＋ Pôr numa coleção…</option>${opts}<option value="new">Nova coleção…</option>`;
  $("#bulkColl").innerHTML = `<option value="">Pôr numa coleção…</option>${opts}<option value="new">Nova coleção…</option>`;
  const cur = colls.find((c) => c.id === state.collection);
  if (state.collection && !cur) state.collection = null;  // foi excluída
  $("#collHead").classList.toggle("hidden", !cur);
  if (cur) {
    $("#collName").textContent = cur.name;
    $("#collInfo").textContent = `${cur.n.toLocaleString("pt-BR")} arquivo${cur.n === 1 ? "" : "s"} · na ordem em que você adicionou`;
  }
  $("#bulkUncoll").classList.toggle("hidden", !cur);
}

async function setFavorite(ids, value) {
  await api("/api/favoritos", { body: { ids, value } });
  for (const it of items) if (ids.includes(it.id)) it.favorite = value ? 1 : 0;
  document.querySelectorAll(".tile").forEach((t) => {
    const it = items.find((x) => x.id === Number(t.dataset.id));
    const s = t.querySelector(".star");
    if (it && s) { s.classList.toggle("on", !!it.favorite); s.textContent = it.favorite ? "★" : "☆"; }
  });
  if (current && ids.includes(current.id)) { current.favorite = value ? 1 : 0; renderMarks(); }
  refreshColls();
}

async function askNewCollection() {
  const name = prompt("Nome da nova coleção (ex.: Leilão Janeiro 2026):");
  return name && name.trim() ? name.trim() : null;
}

async function putInCollection(value, ids) {
  if (!value || !ids.length) return;
  let r;
  if (value === "new") {
    const name = await askNewCollection();
    if (!name) return;
    r = await api("/api/colecoes", { body: { name, ids } });
    toast(`📁 Coleção “${name}” criada com ${r.added} arquivo${r.added === 1 ? "" : "s"}`);
  } else {
    r = await api(`/api/colecoes/${value}/adicionar`, { body: { ids } });
    const c = colls.find((x) => x.id === Number(value));
    toast(r.added ? `📁 ${r.added} adicionado${r.added === 1 ? "" : "s"} a “${c?.name}”` : `Já estava${ids.length > 1 ? "m" : ""} em “${c?.name}”`);
  }
  await refreshColls();
  if (current && ids.includes(current.id)) { current.collections = (await api(`/api/file/${current.id}`)).collections; renderMarks(); }
}

$("#favEntry").addEventListener("click", () => {
  state.favorite = !state.favorite;
  refreshColls(); load();
});
$("#collList").addEventListener("click", (e) => {
  const el = e.target.closest("[data-coll]");
  if (!el) return;
  const id = Number(el.dataset.coll);
  state.collection = state.collection === id ? null : id;
  refreshColls(); load();
});
$("#btnNewColl").addEventListener("click", async () => {
  const name = await askNewCollection();
  if (!name) return;
  const r = await api("/api/colecoes", { body: { name, ids: [...selected] } });
  state.collection = r.id;
  toast(`📁 Coleção “${name}” criada. Use ☑ Selecionar ou o visualizador para pôr arquivos nela.`);
  refreshColls(); load();
});

// cabeçalho da coleção aberta
$("#collPremiere").addEventListener("click", async () => {
  toast("Enviando a coleção para o Premiere…");
  try {
    const r = await api(`/api/colecoes/${state.collection}/premiere`, { method: "POST" });
    toast(`🎬 ${r.imported} importado${r.imported === 1 ? "" : "s"} → pasta “${r.bin}” em ${r.project}${r.offline.length ? ` · ${r.offline.length} em disco desconectado` : ""}`);
  } catch (err) { toast(err.message); }
});
$("#collRename").addEventListener("click", async () => {
  const cur = colls.find((c) => c.id === state.collection);
  const name = prompt("Novo nome da coleção:", cur?.name || "");
  if (!name || !name.trim()) return;
  try { await api(`/api/colecoes/${state.collection}/renomear`, { body: { name } }); } catch (err) { toast(err.message); }
  refreshColls();
});
$("#collDelete").addEventListener("click", async () => {
  const cur = colls.find((c) => c.id === state.collection);
  if (!confirm(`Excluir a coleção “${cur?.name}”?\n\nSó a coleção é apagada. Os arquivos continuam nas pastas e discos de sempre.`)) return;
  await api(`/api/colecoes/${state.collection}`, { method: "DELETE" });
  state.collection = null;
  refreshColls(); load();
});

// visualizador
function renderMarks() {
  const fav = !!current.favorite;
  $("#vfav").classList.toggle("on", fav);
  $("#vfav").textContent = fav ? "★ Favorito" : "☆ Favoritar";
  $("#vcolls").innerHTML = (current.collections || []).map((c) =>
    `<span class="chip coll" title="Coleção">📁 ${esc(c.name)}<button data-uncoll="${c.id}" title="Tirar desta coleção">×</button></span>`).join("");
  $("#vcollAdd").value = "";
}
$("#vfav").addEventListener("click", () => setFavorite([current.id], !current.favorite));
$("#vcollAdd").addEventListener("change", (e) => putInCollection(e.target.value, [current.id]));
$("#vcolls").addEventListener("click", async (e) => {
  const cid = e.target.dataset.uncoll;
  if (!cid) return;
  await api(`/api/colecoes/${cid}/remover`, { body: { ids: [current.id] } });
  current.collections = current.collections.filter((c) => c.id !== Number(cid));
  renderMarks();
  refreshColls();
  if (state.collection === Number(cid)) load();
});

// barra de seleção
$("#bulkFav").addEventListener("click", () => {
  const ids = [...selected];
  const allFav = items.filter((it) => selected.has(it.id)).every((it) => it.favorite);
  setFavorite(ids, !allFav);
  toast(allFav ? `${ids.length} tirado${ids.length === 1 ? "" : "s"} dos favoritos` : `⭐ ${ids.length} nos favoritos`);
});
$("#bulkColl").addEventListener("change", async (e) => {
  await putInCollection(e.target.value, [...selected]);
  e.target.value = "";
});
$("#bulkUncoll").addEventListener("click", async () => {
  const ids = [...selected];
  await api(`/api/colecoes/${state.collection}/remover`, { body: { ids } });
  toast(`${ids.length} tirado${ids.length === 1 ? "" : "s"} da coleção`);
  selected.clear(); syncSelection();
  refreshColls(); load();
});

// ------------------------------------------------------------ gravar palavras-chave nos arquivos (XMP)
let xmpTarget = null;  // { ids } | { collection }

function openXmp(target, label) {
  xmpTarget = target;
  $("#xmpWhat").textContent = label;
  try {
    const m = localStorage.getItem("xmpMode");
    if (m) document.querySelector(`input[name=xmpMode][value=${m}]`).checked = true;
  } catch {}
  $("#xmpDlg").classList.remove("hidden");
}
$("#xmpDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "xmpDlg") $("#xmpDlg").classList.add("hidden");
});
$("#xmpGo").addEventListener("click", async () => {
  const mode = document.querySelector("input[name=xmpMode]:checked").value;
  try { localStorage.setItem("xmpMode", mode); } catch {}
  try {
    const r = await api("/api/xmp", { body: { ...xmpTarget, mode, include_ai: $("#xmpAi").checked } });
    $("#xmpDlg").classList.add("hidden");
    toast(`🏷 Gravando em ${r.count} arquivo${r.count === 1 ? "" : "s"}… o progresso aparece na barra de cima.`);
    pollJobs();
  } catch (err) { toast(err.message); }
});
$("#bulkXmp").addEventListener("click", () =>
  openXmp({ ids: [...selected] }, `${selected.size} arquivo${selected.size === 1 ? "" : "s"} selecionado${selected.size === 1 ? "" : "s"}.`));
$("#collXmp").addEventListener("click", () => {
  const c = colls.find((x) => x.id === state.collection);
  openXmp({ collection: state.collection }, `Todos os ${c?.n ?? ""} arquivos da coleção “${c?.name ?? ""}”.`);
});
$("#vxmp").addEventListener("click", () => openXmp({ ids: [current.id] }, `Arquivo: ${current.name}`));

function xmpSummary(r) {
  const parts = [];
  if (r.dentro) parts.push(`${r.dentro} dentro do arquivo`);
  if (r.sidecar) parts.push(`${r.sidecar} em .xmp ao lado`);
  if (r.sem_palavras) parts.push(`${r.sem_palavras} sem nomes/palavras-chave para gravar`);
  if (r.desconectado) parts.push(`${r.desconectado} em disco desconectado`);
  if (r.erros?.length) parts.push(`${r.erros.length} com erro (${r.erros[0]})`);
  return "🏷 Palavras-chave gravadas: " + (parts.join(" · ") || "nada a gravar");
}

// ------------------------------------------------------------ Premiere
const speechQuery = () => (["auto", "texto", "falado"].includes(state.mode) ? state.q.trim() : "");

async function sendToPremiere(ids, trechos = false) {
  toast("Enviando para o Premiere…");
  try {
    const r = await api("/api/premiere/importar", { body: { ids, q: speechQuery(), trechos } });
    const parts = [`${r.imported} arquivo${r.imported === 1 ? "" : "s"} importado${r.imported === 1 ? "" : "s"}`];
    if (r.subclips) parts.push(`${r.subclips} subclipe${r.subclips > 1 ? "s" : ""} nos trechos falados`);
    if (r.imported === 0 && !r.subclips) parts[0] = "Já estava no projeto";
    if (r.offline.length) parts.push(`${r.offline.length} em disco desconectado`);
    toast(`🎬 ${parts.join(" · ")} → pasta “${r.bin}” em ${r.project}`);
  } catch (err) {
    toast(err.message);
  }
}
$("#vpremiere").addEventListener("click", () => sendToPremiere([current.id]));
$("#vpremiereCut").addEventListener("click", () => sendToPremiere([current.id], true));
$("#bulkPremiere").addEventListener("click", () => {
  const ids = [...selected];
  const hasSpeech = speechQuery() && items.some((it) => selected.has(it.id) && it.match_start != null);
  const trechos = hasSpeech && confirm("Criar também subclipes nos trechos em que a frase é dita?\n\nOK = sim, cada trecho vira um subclipe pronto para arrastar\nCancelar = importar só os arquivos inteiros");
  sendToPremiere(ids, trechos);
});

// ------------------------------------------------------------ duplicados
const fmtBytes = (b) => b >= 1e9 ? (b / 1e9).toFixed(1).replace(".", ",") + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB";
const dup = { prefer: "", kind: "", items: [], remove: new Map() };  // remove: id -> tamanho

async function openDupes() {
  $("#dupesDlg").classList.remove("hidden");
  const vols = volumes.length ? volumes : await api("/api/volumes");
  const sel = $("#dupesPrefer");
  sel.innerHTML = `<option value="">Sugestão automática</option>` +
    vols.map((v) => `<option value="${v.serial}">${esc(v.label)}${v.online ? "" : " (desconectado)"}</option>`).join("");
  sel.value = dup.prefer;
  loadDupes();
  loadTrash();
}
$("#btnDupes").addEventListener("click", openDupes);
$("#dupesDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "dupesDlg") $("#dupesDlg").classList.add("hidden");
});
$("#dupesFind").addEventListener("click", async () => {
  await api("/api/duplicados/procurar", { method: "POST" });
  toast("Procurando duplicados… o progresso aparece na barra da página principal.");
  pollJobs();
});
$("#dupesPrefer").addEventListener("change", (e) => { dup.prefer = e.target.value; loadDupes(); });
$("#dupesKind").addEventListener("click", (e) => {
  if (e.target.dataset.kind === undefined) return;
  dup.kind = e.target.dataset.kind;
  document.querySelectorAll("#dupesKind button").forEach((b) => b.classList.toggle("on", b === e.target));
  loadDupes();
});
$("#dupesMore button").addEventListener("click", () => loadDupes(true));

async function loadDupes(append = false) {
  const p = new URLSearchParams({ prefer: dup.prefer, kind: dup.kind, limit: 100, offset: append ? dup.items.length : 0 });
  const res = await api("/api/duplicados?" + p);
  if (!append) { dup.items = []; dup.remove.clear(); }
  dup.items = dup.items.concat(res.items);
  for (const g of res.items)  // sugestão: remover todas as cópias conectadas menos a que fica
    for (const c of g.copies) if (!c.keep && c.online) dup.remove.set(c.id, c.size);
  $("#dupesSummary").innerHTML = res.groups
    ? `<b>${res.groups.toLocaleString("pt-BR")}</b> arquivos com cópias (${res.extra.toLocaleString("pt-BR")} cópias extras) · <b>${fmtBytes(res.waste)}</b> podem ser liberados`
    : `Nenhum duplicado encontrado ainda. Clique em <b>Procurar duplicados</b> (só discos conectados são conferidos).`;
  $("#dupesMore").classList.toggle("hidden", dup.items.length >= res.groups);
  $("#dupesList").innerHTML = dup.items.map(groupHtml).join("");
  syncDupesBar();
}

function groupHtml(g) {
  const thumb = g.copies.find((c) => c.has_thumb);
  return `<div class="dgroup" data-hash="${g.fhash}">
    ${thumb ? `<img src="/api/thumb/${thumb.id}" alt="">` : `<div class="noimg"></div>`}
    <div>
      <h4>${esc(g.copies[0].name)} <small>· ${fmtBytes(g.size)} · ${g.n} cópias · libera ${fmtBytes(g.waste)}</small></h4>
      ${g.copies.map((c) => {
        const rm = dup.remove.has(c.id);
        return `<div class="dcopy${rm ? "" : " keep"}">
          <input type="checkbox" data-rm="${c.id}" data-size="${c.size}" ${rm ? "checked" : ""} ${c.online ? "" : "disabled"}
                 title="${c.online ? "Marcado = vai para a lixeira" : "Disco desconectado"}">
          <span class="tag">${rm ? "remover" : "manter"}</span>
          <span class="p">${esc(c.full_path)}${c.my_tags ? " · tem marcações suas (palavras-chave, ⭐ ou coleção)" : ""}</span>
          ${c.online ? `<button data-explore-dup="${c.id}" title="Mostrar no Explorer">📂</button>` : `<span class="tag">desconectado</span>`}
        </div>`;
      }).join("")}
    </div></div>`;
}

$("#dupesList").addEventListener("click", (e) => {
  if (e.target.dataset.exploreDup) showInExplorer(Number(e.target.dataset.exploreDup));
});
$("#dupesList").addEventListener("change", (e) => {
  const id = Number(e.target.dataset.rm);
  if (!id) return;
  const group = e.target.closest(".dgroup");
  const boxes = [...group.querySelectorAll("input[data-rm]")];
  if (e.target.checked && boxes.every((b) => b.checked)) {
    e.target.checked = false;
    toast("Pelo menos uma cópia precisa ficar.");
    return;
  }
  if (e.target.checked) dup.remove.set(id, Number(e.target.dataset.size)); else dup.remove.delete(id);
  const row = e.target.closest(".dcopy");
  row.classList.toggle("keep", !e.target.checked);
  row.querySelector(".tag").textContent = e.target.checked ? "remover" : "manter";
  syncDupesBar();
});

function syncDupesBar() {
  const n = dup.remove.size;
  const bytes = [...dup.remove.values()].reduce((a, b) => a + b, 0);
  $("#dupesSel").textContent = n ? `${n.toLocaleString("pt-BR")} cópias marcadas · ${fmtBytes(bytes)}` : "Nenhuma cópia marcada";
  $("#dupesTrash").disabled = !n;
  $("#dupesTrash").textContent = n ? `Mover ${n.toLocaleString("pt-BR")} para a lixeira` : "Mover para a lixeira";
}

$("#dupesTrash").addEventListener("click", async () => {
  const n = dup.remove.size;
  if (!n || !confirm(`Mover ${n} cópias duplicadas para a lixeira do BuscadorFAST?\n\nElas saem das pastas, mas dá para restaurar. O espaço só é liberado ao esvaziar a lixeira.`)) return;
  $("#dupesTrash").disabled = true;
  $("#dupesTrash").textContent = "Movendo…";
  const r = await api("/api/duplicados/lixeira", { body: { ids: [...dup.remove.keys()] } });
  toast(`${r.moved} cópias movidas (${fmtBytes(r.bytes)})${r.refused.length ? ` · ${r.refused.length} recusadas: ${r.refused[0].motivo}` : ""}`);
  loadDupes();
  loadTrash();
  refreshSide();
});

async function loadTrash() {
  const t = await api("/api/lixeira");
  $("#trashList").innerHTML = t.map((d) => `
    <div class="trow">
      <span class="n"><b>${esc(d.label)}</b> · ${d.n.toLocaleString("pt-BR")} arquivos · ${fmtBytes(d.bytes)}${d.online ? "" : " · disco desconectado"}</span>
      <button class="ghost" data-restore="${d.serial}" ${d.online ? "" : "disabled"}>Restaurar tudo</button>
      <button class="danger-solid" data-empty="${d.serial}" data-label="${esc(d.label)}" data-bytes="${d.bytes}" ${d.online ? "" : "disabled"}>Esvaziar e liberar ${fmtBytes(d.bytes)}</button>
    </div>`).join("") || `<div class="muted">A lixeira está vazia.</div>`;
}
$("#trashList").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.restore) {
    const r = await api("/api/lixeira/restaurar", { body: { serial: b.dataset.restore } });
    toast(`${r.restored} arquivos voltaram para o lugar${r.failed ? ` · ${r.failed} não puderam voltar` : ""}`);
  } else if (b.dataset.empty) {
    if (!confirm(`Apagar DE VEZ os duplicados da lixeira do disco ${b.dataset.label}?\n\nIsso libera ${fmtBytes(Number(b.dataset.bytes))} e NÃO pode ser desfeito. As cópias mantidas continuam nos seus lugares.`)) return;
    b.disabled = true; b.textContent = "Apagando…";
    const r = await api("/api/lixeira/esvaziar", { body: { serial: b.dataset.empty } });
    toast(`${r.deleted} arquivos apagados · ${fmtBytes(r.bytes)} liberados`);
  }
  loadTrash(); loadDupes(); refreshSide();
});

// ------------------------------------------------------------ backup
const ago = (iso) => {
  if (!iso) return "nunca";
  const h = (Date.now() - new Date(iso)) / 36e5;
  return h < 1 ? "há menos de 1 hora" : h < 48 ? `há ${Math.round(h)} h` : `há ${Math.round(h / 24)} dias`;
};

async function loadBackup() {
  const b = await api("/api/backup");
  const stale = !b.last || (Date.now() - new Date(b.last)) / 36e5 > 72;
  $("#settingsDot").classList.toggle("hidden", !(b.last_error || stale));
  const st = $("#bkStatus");
  st.className = "bk-status " + (b.last_error ? "bad" : b.last && !stale ? "ok" : "");
  st.innerHTML = b.last_error
    ? `⚠ Último backup falhou: ${esc(b.last_error)}`
    : b.last ? `✓ Último backup ${ago(b.last)} em <b>${esc(b.path)}</b>` : "Nenhum backup feito ainda.";
  $("#bkList").innerHTML = b.backups.map((x) =>
    `<div class="trow"><span class="n">${new Date(x.date).toLocaleString("pt-BR")}</span><span class="muted">${fmtBytes(x.size)}</span><code>${esc(x.name)}</code></div>`
  ).join("") || `<div class="muted">${b.online ? "Nenhum ainda." : "O disco de destino está desconectado."}</div>`;
  return b;
}

async function openSettings() {
  $("#settingsDlg").classList.remove("hidden");
  const [b, drives] = await Promise.all([loadBackup(), api("/api/drives")]);
  $("#bkDest").innerHTML = drives.filter((d) => d.letter !== b.program_drive)  // backup no mesmo disco não protege
    .map((d) => `<option value="${d.letter}:\\">${d.letter}: ${esc(d.label)}</option>`).join("");
  $("#bkDest").value = b.dest;
  $("#bkKeep").value = String(b.keep);
}
$("#btnSettings").addEventListener("click", openSettings);
$("#settingsDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "settingsDlg") $("#settingsDlg").classList.add("hidden");
});
$("#bkForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/backup/config", { body: { dest: $("#bkDest").value, keep: Number($("#bkKeep").value) } });
    toast("Configuração do backup salva.");
    loadBackup();
  } catch (err) { toast(err.message); }
});
$("#bkNow").addEventListener("click", async () => {
  const b = $("#bkNow");
  b.disabled = true; b.textContent = "Fazendo backup…";
  try {
    const r = await api("/api/backup/agora", { method: "POST" });
    toast(`Backup feito: ${fmtBytes(r.size)} em ${r.seconds}s`);
  } catch (err) { toast(err.message); }
  b.disabled = false; b.textContent = "Fazer backup agora";
  loadBackup();
});

// ------------------------------------------------------------ baixar
const RAW_EXTS = [".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".nrw"];

function renderDownload() {
  const f = current;
  const down = $("#vdown"), jpg = $("#vdownJpg");
  const raw = RAW_EXTS.includes(f.ext);
  down.href = `/api/media/${f.id}?baixar=true`;
  down.textContent = `Baixar${raw ? " RAW" : ""} (${fmtBytes(f.size || 0)})`;
  down.classList.toggle("off", !f.online);
  down.title = f.online ? "" : "Disco desconectado";
  jpg.classList.toggle("hidden", !raw);
  // RAW: o JPG é o que abre no celular, então ele vira o botão principal
  down.classList.toggle("ghost", raw);
  jpg.classList.toggle("ghost", !raw);
  jpg.href = `/api/media/${f.id}?baixar=true&jpg=true`;
  jpg.classList.toggle("off", !f.online);
}

function downloadUrl(url) {
  const a = document.createElement("a");
  a.href = url; a.download = "";
  document.body.appendChild(a); a.click(); a.remove();
}

// ------------------------------------------------------------ iPhone: folha de compartilhamento
// No iPhone, um link de download abre direto o arquivo num app (WhatsApp, AnyDesk…) sem mostrar as opções.
// Aqui o arquivo é baixado primeiro e entregue à folha de compartilhamento do sistema, que tem
// "Salvar imagem/vídeo" (vai para Fotos), "Salvar em Arquivos", AirDrop e os apps.
const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const SHARE_MAX = 1.5e9;  // acima disso o Safari pode ficar sem memória: usa o download comum
let shareCtl = null, shareFile = null;

function canShareFiles() {
  try {
    return IS_IOS && !!navigator.canShare && navigator.canShare({ files: [new File(["x"], "x.txt", { type: "text/plain" })] });
  } catch { return false; }
}

function shareUi(msg, pct = null, ready = false) {
  $("#shareBox").classList.remove("hidden");
  $("#shareMsg").textContent = msg;
  $("#shareBar").parentElement.classList.toggle("hidden", pct === null);
  if (pct !== null) $("#shareBar").style.width = `${Math.round(pct * 100)}%`;
  $("#shareGo").classList.toggle("hidden", !ready);
}
function shareClose() {
  if (shareCtl) shareCtl.abort();
  shareCtl = null; shareFile = null;
  $("#shareBox").classList.add("hidden");
}

function nameFrom(res, url) {
  const cd = res.headers.get("Content-Disposition") || "";
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) { try { return decodeURIComponent(star[1]); } catch {} }
  const plain = cd.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : (url.split("/").pop().split("?")[0] || "arquivo");
}

async function shareNow() {
  if (!shareFile) return;
  try {
    await navigator.share({ files: [shareFile] });
    shareClose();
  } catch (err) {
    if (err.name === "AbortError") { shareClose(); return; }  // a pessoa fechou a folha
    if (err.name === "NotAllowedError") {  // o iPhone exige um toque logo antes de abrir a folha
      shareUi(`Pronto: ${shareFile.name}`, null, true);
      return;
    }
    shareClose();
    toast(`Não deu para compartilhar: ${err.message}`);
  }
}

async function shareDownload(url, size = 0) {
  if (size > SHARE_MAX) return false;
  shareClose();
  shareCtl = new AbortController();
  shareUi("Preparando o arquivo…", 0);
  try {
    const res = await fetch(url, { signal: shareCtl.signal });
    if (!res.ok) throw new Error(res.status === 404 ? "arquivo não encontrado (disco desconectado?)" : `erro ${res.status}`);
    const name = nameFrom(res, url);
    const total = Number(res.headers.get("Content-Length")) || size || 0;
    const reader = res.body.getReader();
    const parts = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value); got += value.length;
      shareUi(`Preparando ${name}… ${fmtBytes(got)}${total ? " de " + fmtBytes(total) : ""}`, total ? got / total : null);
    }
    const type = (res.headers.get("Content-Type") || "application/octet-stream").split(";")[0];
    shareFile = new File(parts, name, { type });
    shareUi(`Pronto: ${name}`, null, true);
    await shareNow();  // tenta abrir direto; se o iPhone pedir outro toque, o botão já está na tela
  } catch (err) {
    if (err.name === "AbortError") return true;
    shareClose();
    toast(`Não deu para baixar: ${err.message}`);
  }
  return true;
}

$("#shareGo").addEventListener("click", shareNow);
$("#shareCancel").addEventListener("click", shareClose);

// links de download de um arquivo só (visualizador e caixa de transferência); o .zip continua como download
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[download]");
  if (!a || !a.href || a.classList.contains("off") || !canShareFiles()) return;
  if (!/baixar=true|\/caixa\/\d+\/baixar/.test(a.href)) return;
  const size = a.id === "vdown" ? (current?.size || 0) : 0;
  if (size > SHARE_MAX) return;  // grande demais: segue o download comum
  e.preventDefault();
  shareDownload(a.href, size);
});

$("#bulkDown").addEventListener("click", () => {
  const ids = [...selected];
  if (ids.length === 1) {
    const one = items.find((it) => it.id === ids[0]);
    if (canShareFiles() && (one?.size || 0) <= SHARE_MAX) return shareDownload(`/api/media/${ids[0]}?baixar=true`, one?.size || 0);
    return downloadUrl(`/api/media/${ids[0]}?baixar=true`);
  }
  const bytes = items.filter((it) => selected.has(it.id)).reduce((a, it) => a + (it.size || 0), 0);
  if (!confirm(`Baixar ${ids.length} arquivos num .zip (${fmtBytes(bytes)})?${bytes > 2e9 ? "\n\nÉ bastante coisa: no celular pode demorar e ocupar espaço." : ""}\n\nArquivos em discos desconectados ficam de fora.`)) return;
  const name = state.collection ? colls.find((c) => c.id === state.collection)?.name : state.q.trim();
  downloadUrl(`/api/baixar?ids=${ids.join(",")}${name ? "&nome=" + encodeURIComponent("BuscadorFAST - " + name) : ""}`);
  toast(`⬇ Preparando o .zip com ${ids.length} arquivos… o download começa em instantes.`);
});

// ------------------------------------------------------------ transferir entre PC e celular
let xferTimer = null;

async function openXfer() {
  $("#xferDlg").classList.remove("hidden");
  await loadXfer();
  clearInterval(xferTimer);
  xferTimer = setInterval(() => {  // acompanha o que chega do outro lado
    if ($("#xferDlg").classList.contains("hidden")) return clearInterval(xferTimer);
    loadXfer();
  }, 5000);
}
$("#btnXfer").addEventListener("click", openXfer);
$("#xferDlg").addEventListener("click", (e) => {
  if (e.target.dataset.close !== undefined || e.target.id === "xferDlg") $("#xferDlg").classList.add("hidden");
});

async function loadXfer() {
  const r = await api("/api/transferir");
  $("#xferDest").textContent = r.dest;
  if (document.activeElement !== $("#xferDestInput")) $("#xferDestInput").value = r.dest;
  const remote = document.body.classList.contains("remote");
  $("#recvList").innerHTML = r.received.map((f) => `
    <div class="xrow">
      ${f.file_id ? `<img src="/api/thumb/${f.file_id}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'📄'}))">` : `<span class="ph">📄</span>`}
      <span class="n">${esc(f.name)}<small>${fmtBytes(f.size)} · ${new Date(f.when).toLocaleString("pt-BR")}${f.file_id || !f.media ? "" : " · indexando…"}</small></span>
      ${f.file_id ? `<button class="ghost" data-view="${f.file_id}">Ver</button>` : ""}
      ${f.file_id && !remote ? `<button class="ghost" data-explore-x="${f.file_id}" title="Mostrar no Explorer">📂</button>` : ""}
    </div>`).join("") || `<div class="muted small">Nada recebido ainda.</div>`;
  $("#outList").innerHTML = r.outbox.map((o) => `
    <div class="xrow">
      ${o.file_id && o.has_thumb ? `<img src="/api/thumb/${o.file_id}" alt="">` : `<span class="ph">📄</span>`}
      <span class="n">${esc(o.name)}<small>${fmtBytes(o.size || 0)} · ${new Date(o.added).toLocaleString("pt-BR")}</small></span>
      <a class="btn" href="/api/transferir/caixa/${o.id}/baixar" download>⬇ Baixar</a>
      <button class="ghost" data-unbox="${o.id}" title="Tirar da caixa do celular (o original continua no PC)">✕</button>
    </div>`).join("") || `<div class="muted small">A caixa do celular está vazia.</div>`;
}

$("#recvList").addEventListener("click", (e) => {
  const v = e.target.dataset.view, x = e.target.dataset.exploreX;
  if (v) { $("#xferDlg").classList.add("hidden"); openViewer(Number(v)); }
  if (x) showInExplorer(Number(x));
});
$("#outList").addEventListener("click", async (e) => {
  const id = e.target.dataset.unbox;
  if (!id) return;
  await api(`/api/transferir/caixa/${id}`, { method: "DELETE" });
  loadXfer();
});

// envio em sequência, com barra de progresso por arquivo
function uploadOne(file) {
  const row = document.createElement("div");
  row.className = "upitem";
  row.innerHTML = `<span class="n">${esc(file.name)}</span><span class="p">${fmtBytes(file.size)}</span><div class="bar"><i></i></div>`;
  $("#upList").prepend(row);
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const q = new URLSearchParams({ nome: file.name, modificado: file.lastModified || "" });
    xhr.open("PUT", "/api/transferir/enviar?" + q);
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      row.querySelector(".bar i").style.width = (100 * e.loaded / e.total) + "%";
      row.querySelector(".p").textContent = `${Math.round(100 * e.loaded / e.total)}% de ${fmtBytes(file.size)}`;
    };
    xhr.onload = () => {
      const ok = xhr.status === 200;
      row.classList.add(ok ? "done" : "fail");
      row.querySelector(".p").textContent = ok ? "✓ enviado" : "falhou";
      resolve(ok);
    };
    xhr.onerror = () => { row.classList.add("fail"); row.querySelector(".p").textContent = "falhou (conexão caiu?)"; resolve(false); };
    xhr.send(file);
  });
}

async function uploadMany(files) {
  files = [...files];
  if (!files.length) return;
  let ok = 0;
  for (const f of files) ok += await uploadOne(f) ? 1 : 0;
  if (ok) await api("/api/transferir/concluir", { method: "POST" });
  toast(`✓ ${ok} de ${files.length} enviado${files.length === 1 ? "" : "s"} para o PC${ok ? " · entrando no catálogo…" : ""}`);
  loadXfer();
}
$("#upMedia").addEventListener("change", (e) => { uploadMany(e.target.files); e.target.value = ""; });
$("#upAny").addEventListener("change", (e) => { uploadMany(e.target.files); e.target.value = ""; });

// PC: escolher arquivos na janela do Windows (a caixa guarda só o caminho, sem copiar)
$("#pickOut").addEventListener("click", async () => {
  const b = $("#pickOut");
  b.disabled = true; b.textContent = "Escolha na janela do Windows…";
  try {
    const r = await api("/api/transferir/escolher", { method: "POST" });
    if (r.added) toast(`📱 ${r.added} arquivo${r.added === 1 ? "" : "s"} na caixa do celular`);
  } catch (err) { toast(err.message); }
  b.disabled = false; b.textContent = "📂 Escolher arquivos no PC";
  loadXfer();
});

$("#xferDestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/transferir/destino", { body: { dest: $("#xferDestInput").value } });
    toast("Pasta de chegada alterada.");
    loadXfer();
  } catch (err) { toast(err.message); }
});
$("#xferOpen").addEventListener("click", () => api("/api/transferir/abrir-pasta", { method: "POST" }));

$("#bulkToPhone").addEventListener("click", async () => {
  const r = await api("/api/transferir/caixa", { body: { ids: [...selected] } });
  toast(`📱 ${r.added} arquivo${r.added === 1 ? "" : "s"} na caixa do celular. No celular: ⇄ Transferir.`);
});

// ------------------------------------------------------------ acesso pelo celular
async function loadLan() {
  const r = await api("/api/rede");
  $("#lanOn").checked = r.enabled;
  $("#lanBox").classList.toggle("hidden", !r.enabled);
  if (r.enabled) {
    $("#lanQr").innerHTML = r.qr;
    $("#lanUrl").textContent = r.url;
    $("#lanUrlPlain").textContent = r.url_simples || "";
  }
  $("#awayBox").classList.toggle("hidden", !r.enabled);
  if (r.enabled) renderAway(r.fora || { installed: false });
}

// ------------------------------------------------------------ fora de casa (Tailscale)
function renderAway(t, extra = "") {
  const check = `<button class="ghost" data-away="check">↻ Verificar de novo</button>`;
  let h;
  if (!t.installed) {
    h = `<ol class="steps">
        <li>Instale o <b>Tailscale</b> neste PC: <a href="https://tailscale.com/download/windows" target="_blank" rel="noopener">tailscale.com/download</a> e entre com uma conta (Google, Microsoft…).</li>
        <li>Instale o app <b>Tailscale</b> no celular (Play Store / App Store) e entre com a <b>mesma conta</b>.</li>
        <li>Volte aqui e toque em <i>Verificar de novo</i>: aparece o QR code para usar fora de casa.</li>
      </ol>${check}`;
  } else if (!t.running) {
    h = `<p>O Tailscale está instalado, mas ${t.state === "NeedsLogin" ? "<b>falta entrar na sua conta</b>" : "<b>desligado</b>"}. Abra o Tailscale pelo ícone perto do relógio e conecte.</p>${check}`;
  } else {
    h = `<div class="lan">
        <div class="qr">${t.qr}</div>
        <div class="lan-info">
          <p>Com o Tailscale <b>ligado no celular</b>, leia este QR code — funciona em qualquer lugar.</p>
          <p class="muted small">Endereço: <code>${esc(t.url)}</code></p>
          ${t.https
            ? `<p class="ok small">✓ Endereço seguro (HTTPS) ligado: a busca por voz 🎤 funciona e o celular não mostra aviso.</p>`
            : `<p class="small">Para a <b>busca por voz</b> funcionar fora de casa, ligue o endereço seguro do Tailscale (<code>${esc(t.name || "")}</code>):</p>
               <button data-away="https">🔒 Ligar endereço seguro (HTTPS)</button>
               <p class="muted small">Sem ele, o resto funciona normalmente (a conexão já é criptografada pelo Tailscale). Se não abrir, o Windows pode pedir permissão no <b>Firewall</b> para o “Python”.</p>`}
          ${extra}
        </div>
      </div>`;
  }
  $("#awayBody").innerHTML = h;
}
$("#awayBody").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-away]");
  if (!b) return;
  b.disabled = true;
  if (b.dataset.away === "check") {
    await loadLan().catch(() => {});
    return;
  }
  b.textContent = "Ligando…";
  const r = await api("/api/rede/fora-https", { method: "POST" }).catch((err) => ({ ok: false, error: err.message }));
  if (r.ok) { toast("🔒 Endereço seguro ligado. Leia o QR code de novo no celular."); renderAway(r); return; }
  const st = await api("/api/rede").then((x) => x.fora).catch(() => null);
  renderAway(st || { installed: true, running: false }, r.enable_url
    ? `<p class="small warn">${esc(r.error)} <a href="${esc(r.enable_url)}" target="_blank" rel="noopener">Abrir a página do Tailscale</a>, clicar em <b>Enable</b> e depois tocar de novo em <i>Ligar endereço seguro</i>.</p>`
    : `<p class="small warn">Não deu certo: ${esc(r.error || "")}</p>`);
});
$("#lanOn").addEventListener("change", async (e) => {
  await api("/api/rede", { body: { on: e.target.checked } });
  toast(e.target.checked ? "Acesso pelo celular ligado. Leia o QR code com a câmera." : "Acesso pelo celular desligado.");
  loadLan();
});
$("#lanNewKey").addEventListener("click", async () => {
  if (!confirm("Gerar uma nova chave? Celulares que usavam o QR code antigo vão precisar ler o novo.")) return;
  await api("/api/rede/nova-chave", { method: "POST" });
  loadLan();
});
$("#btnSettings").addEventListener("click", () => { loadLan().catch(() => {}); loadSchedule().catch(() => {}); });

// ------------------------------------------------------------ atualização automática à noite
async function loadSchedule() {
  const s = await api("/api/agenda");
  $("#schedOn").checked = s.enabled;
  $("#schedStart").value = s.start.padStart(5, "0");
  $("#schedStop").value = s.stop.padStart(5, "0");
}
async function saveSchedule() {
  try {
    const s = await api("/api/agenda", { body: { on: $("#schedOn").checked, start: $("#schedStart").value, stop: $("#schedStop").value } });
    toast(s.enabled ? `🌙 Atualização automática: todo dia das ${s.start} às ${s.stop}.` : "Atualização automática desligada.");
    loadSchedule();
  } catch (err) { toast(err.message); loadSchedule(); }
}
$("#schedOn").addEventListener("change", saveSchedule);
$("#schedSave").addEventListener("click", () => { $("#schedOn").checked = true; saveSchedule(); });

$("#btnQuit").addEventListener("click", async () => {
  const running = !$("#jobBar").classList.contains("hidden");
  if (!confirm(running ? "Fechar o BuscadorFAST? A tarefa em andamento será parada (o que já foi feito fica salvo)." : "Fechar o BuscadorFAST?")) return;
  await api("/api/sair", { method: "POST" }).catch(() => {});
  clearTimeout(pollTimer);
  document.body.innerHTML = `<div class="empty">BuscadorFAST fechado.<br><br>Para abrir de novo, use o atalho <b>BuscadorFAST</b> na área de trabalho.</div>`;
});

// ------------------------------------------------------------ início
// celular: o painel de filtros abre por cima, com "Ver resultados" no rodapé
function openFilters(on) {
  document.body.classList.toggle("show-filters", on);
  document.querySelectorAll('#bottomNav button').forEach((b) => b.classList.toggle("on", b.dataset.nav === (on ? "filters" : "home")));
  if (!on) window.scrollTo({ top: 0, behavior: "smooth" });
}
$("#filtersClose").addEventListener("click", () => openFilters(false));
$("#filtersApply").addEventListener("click", () => openFilters(false));
$("#filtersReset").addEventListener("click", () => clearAllFilters());
api("/api/eu").then((r) => document.body.classList.toggle("remote", r.remote)).catch(() => {});
refreshSide().then(() => load());
pollJobs();
loadBackup().catch(() => {});  // acende o ponto vermelho no ⚙ se o backup falhou ou está atrasado
loadHealth().catch(() => {});  // ⚠ ao lado de "Saúde dos discos" se algum disco precisar de atenção

// ------------------------------------------------------------ interface (atalhos, menus, celular)
function activeCount() {
  return [state.favorite, state.photo, state.area, state.album, state.review, state.similar, state.volume, state.camera,
    state.dateFrom || state.dateTo, state.kind].filter(Boolean).length + state.tags.length + (state.people.length ? 1 : 0);
}
function clearAllFilters() {
  Object.assign(state, { favorite: false, photo: null, area: "", album: null, review: false, similar: null, volume: null,
    camera: "", dateFrom: "", dateTo: "", tags: [], kind: "", collection: null, people: [] });
  renderSidePeople();
  $("#camera").value = ""; $("#dateFrom").value = $("#dateTo").value = "";
  tl.year = tl.month = tl.day = "";
  document.querySelectorAll("#kindSeg button").forEach((b) => b.classList.toggle("on", b.dataset.kind === ""));
  document.querySelectorAll("#quickDates button").forEach((b) => b.classList.remove("on"));
  $("#collHead")?.classList.add("hidden"); $("#reviewHead")?.classList.add("hidden");
  refreshSide(); load();
}
$("#clearAll").addEventListener("click", clearAllFilters);

// datas rápidas
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
$("#quickDates").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  const now = new Date(), y = now.getFullYear();
  let from, to = isoDay(now);
  if (b.classList.contains("on")) { from = to = ""; }
  else if (b.dataset.range === "30") from = isoDay(new Date(now - 30 * 864e5));
  else if (b.dataset.range === "month") from = isoDay(new Date(y, now.getMonth(), 1));
  else if (b.dataset.range === "year") from = `${y}-01-01`;
  else { from = `${y - 1}-01-01`; to = `${y - 1}-12-31`; }
  document.querySelectorAll("#quickDates button").forEach((x) => x.classList.toggle("on", x === b && !!from));
  state.dateFrom = from; state.dateTo = to; $("#dateFrom").value = from; $("#dateTo").value = to;
  load();
});
["#dateFrom", "#dateTo"].forEach((s) => $(s).addEventListener("change", () =>
  document.querySelectorAll("#quickDates button").forEach((x) => x.classList.remove("on"))));

// palavras-chave: filtro e "ver todas"
function filterTags() {
  const f = $("#tagFilter").value.trim().toLowerCase();
  $("#tagCloud").classList.toggle("filtering", !!f);
  document.querySelectorAll("#tagCloud span").forEach((el) => el.classList.toggle("hidden", !!f && !el.dataset.t.toLowerCase().includes(f)));
}
$("#tagFilter").addEventListener("input", filterTags);
$("#tagMore").addEventListener("click", () => {
  const c = $("#tagCloud").classList.toggle("collapsed");
  $("#tagMore").textContent = c ? "Ver todas" : "Ver menos";
});
$("#tagCloud").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); } });

// menu Ferramentas
function toolsMenu(on) {
  $("#toolsMenu").classList.toggle("hidden", !on);
  $("#btnTools").setAttribute("aria-expanded", on);
  if (on) $("#toolsMenu button").focus();
}
$("#btnTools").addEventListener("click", (e) => { e.stopPropagation(); toolsMenu($("#toolsMenu").classList.contains("hidden")); });
$("#toolsMenu").addEventListener("click", () => toolsMenu(false));
document.addEventListener("click", (e) => { if (!e.target.closest(".menuwrap")) toolsMenu(false); });
$("#toolsMenu").addEventListener("keydown", (e) => {
  const all = [...document.querySelectorAll("#toolsMenu button")], i = all.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length].focus(); }
  if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length].focus(); }
  if (e.key === "Escape") { toolsMenu(false); $("#btnTools").focus(); }
});
$("#btnHealthTop").addEventListener("click", () => $("#btnHealth").click());

// atalho "/" para buscar; Enter/espaço abre a miniatura focada pelo teclado
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(e.target.tagName);
  if (e.key === "/" && !typing && $("#viewer").classList.contains("hidden")) { e.preventDefault(); $("#q").focus(); $("#q").select(); }
  if ((e.key === "Enter" || e.key === " ") && e.target.classList?.contains("tile")) { e.preventDefault(); e.target.click(); }
});

// barra de tarefa: uma linha só; os detalhes das frentes abrem com um toque
let jobOpen = (() => { try { return localStorage.getItem("jobOpen") === "1"; } catch { return false; } })();
document.body.classList.toggle("job-open", jobOpen);
$("#jobBar").addEventListener("click", (e) => {
  if (e.target.closest("button")) return;
  jobOpen = !jobOpen;
  document.body.classList.toggle("job-open", jobOpen);
  try { localStorage.setItem("jobOpen", jobOpen ? "1" : "0"); } catch {}
});

// navegação de baixo (celular)
$("#bottomNav").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  const nav = b.dataset.nav;
  if (nav === "home") { openFilters(false); window.scrollTo({ top: 0, behavior: "smooth" }); }
  else if (nav === "filters") openFilters(!document.body.classList.contains("show-filters"));
  else if (nav === "people") { openFilters(false); $("#btnPeople").click(); }
  else if (nav === "albums") { openFilters(false); $("#albumsEntry").click(); }
  else if (nav === "more") $("#moreSheet").classList.remove("hidden");
});
$("#moreSheet").addEventListener("click", (e) => {
  if (e.target === $("#moreSheet") || e.target.closest("[data-close]")) { $("#moreSheet").classList.add("hidden"); return; }
  const go = e.target.closest("[data-go]")?.dataset.go;
  if (!go) return;
  $("#moreSheet").classList.add("hidden");
  $({ fav: "#favEntry", review: "#reviewEntry", xfer: "#btnXfer", timeline: "#btnTimeline", map: "#btnMap" }[go]).click();
});

// celular: o topo some ao rolar para baixo e volta ao rolar para cima (mais espaço para as fotos)
let lastY = 0;
window.addEventListener("scroll", () => {
  if (window.innerWidth > 800) return;
  const y = window.scrollY;
  document.body.classList.toggle("top-hidden", y > lastY && y > 120 && document.activeElement !== $("#q"));
  lastY = y;
}, { passive: true });

// visualizador: setas na tela (o atalho do teclado não é óbvio) e deslizar o dedo no celular
function stepViewer(d) {
  if (!current) return;
  const i = items.findIndex((x) => x.id === current.id) + d;
  if (items[i]) openViewer(items[i].id);
}
$("#vprev").addEventListener("click", (e) => { e.stopPropagation(); stepViewer(-1); });
$("#vnext").addEventListener("click", (e) => { e.stopPropagation(); stepViewer(1); });
let touchX = null, touchY = null;
$("#vmedia").addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; touchY = e.touches[0].clientY; }, { passive: true });
$("#vmedia").addEventListener("touchend", (e) => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX, dy = e.changedTouches[0].clientY - touchY;
  touchX = null;
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5 && !e.target.closest("video")) stepViewer(dx < 0 ? 1 : -1);
}, { passive: true });

// ------------------------------------------------------------ combinar pessoas
// state.people = [{id, name}]; state.peopleMode = "juntas" | "qualquer" | "so"
const combine = new Map();  // pessoas marcadas na janela Pessoas (id → nome)
const PM_LABEL = { juntas: "juntas", qualquer: "qualquer uma", so: "só elas" };
let combineMode = "juntas";

function peopleParams(p) {
  if (!state.people.length) return;
  p.set("pessoas", state.people.map((x) => x.id).join(","));
  p.set("pessoas_modo", state.peopleMode);
}
function peopleLabel() {
  const names = state.people.map((x) => x.name);
  const joined = names.length > 1 ? names.slice(0, -1).join(", ") + (state.peopleMode === "qualquer" ? " ou " : " e ") + names.at(-1) : names[0];
  return state.people.length > 1 || state.peopleMode === "so" ? `${joined} (${PM_LABEL[state.peopleMode]})` : joined;
}

function togglePick(id, name) {
  combine.has(id) ? combine.delete(id) : combine.set(id, name);
  const card = document.querySelector(`#peopleNamed .pcard[data-person="${id}"]`);
  card?.classList.toggle("picked", combine.has(id));
  card?.querySelector(".ppick")?.setAttribute("aria-pressed", combine.has(id));
  renderCombine();
}
let combineSeq = 0;
async function renderCombine() {
  const on = combine.size > 0;
  $("#combineBar").classList.toggle("active", on);
  $("#combineBar .combine-hint").classList.toggle("hidden", on);
  $("#combineBar .combine-sel").classList.toggle("hidden", !on);
  $("#combineNames").innerHTML = [...combine].map(([id, n]) => `<span class="chip">${esc(n)}<button data-unpick="${id}" aria-label="Tirar ${esc(n)}">×</button></span>`).join("");
  document.querySelectorAll("#combineMode button").forEach((b) => b.classList.toggle("on", b.dataset.pm === combineMode));
  $("#combineMode").classList.toggle("hidden", combine.size < 2 && combineMode !== "so");
  if (!on) return;
  // prévia: quantos arquivos essa combinação acha (respeita "só discos conectados")
  const seq = ++combineSeq;
  $("#combineCount").textContent = "contando…";
  const p = new URLSearchParams({ pessoas: [...combine.keys()].join(","), pessoas_modo: combineMode, limit: 1, only_online: state.onlyOnline });
  const r = await api("/api/search?" + p).catch(() => null);
  if (seq !== combineSeq) return;
  const n = r?.total ?? 0;
  $("#combineCount").textContent = n ? `${n.toLocaleString("pt-BR")} foto${n > 1 ? "s" : ""} e vídeo${n > 1 ? "s" : ""}` : "nenhuma foto com essa combinação";
  $("#combineShow").disabled = !n;
}
$("#combineNames").addEventListener("click", (e) => {
  const id = e.target.dataset.unpick;
  if (id) togglePick(Number(id));
});
$("#combineMode").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pm]");
  if (b) { combineMode = b.dataset.pm; renderCombine(); }
});
$("#combineClear").addEventListener("click", () => {
  [...combine.keys()].forEach((id) => togglePick(id));
});
$("#combineShow").addEventListener("click", () => {
  state.people = [...combine].map(([id, name]) => ({ id, name }));
  state.peopleMode = combine.size > 1 || combineMode === "so" ? combineMode : "juntas";
  state.q = ""; $("#q").value = ""; state.similar = null; state.photo = null;
  $("#peopleDlg").classList.add("hidden");
  renderSidePeople(); load();
});

// lateral: quem está no filtro, como combinar e "escolher pessoas"
function renderSidePeople() {
  $("#sidePeopleList").innerHTML = state.people.map((x) => `<span class="chip">${esc(x.name)}<button data-pdel="${x.id}" aria-label="Tirar ${esc(x.name)}">×</button></span>`).join("");
  $("#sidePeopleMode").classList.toggle("hidden", state.people.length < 2);
  document.querySelectorAll("#sidePeopleMode button").forEach((b) => b.classList.toggle("on", b.dataset.pm === state.peopleMode));
  $("#sidePeopleAdd").textContent = state.people.length ? "＋ Adicionar pessoa" : "Escolher pessoas…";
}
$("#sidePeopleList").addEventListener("click", (e) => {
  const id = Number(e.target.dataset.pdel);
  if (!id) return;
  state.people = state.people.filter((x) => x.id !== id);
  renderSidePeople(); load();
});
$("#sidePeopleMode").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pm]");
  if (!b) return;
  state.peopleMode = b.dataset.pm; renderSidePeople(); load();
});
$("#sidePeopleAdd").addEventListener("click", () => {
  // abre a janela Pessoas já com quem está no filtro marcado
  combine.clear(); state.people.forEach((x) => combine.set(x.id, x.name));
  combineMode = state.peopleMode;
  if (typeof openFilters === "function" && document.body.classList.contains("show-filters")) openFilters(false);
  openPeople().then(renderCombine);
});
renderSidePeople();
