/* CacheNet Lab. Talks only to ui.py's HTTP API; ui.py speaks CNTP to the proxy. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SVGNS = "http://www.w3.org/2000/svg";
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = {
  get(k, d) { try { const v = localStorage.getItem("cachenet." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("cachenet." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const state = { config: null, health: null, history: [], stats: null, statsAt: 0, selected: null, datasets: [], chosen: null, results: null };
const RESOURCES = ["/", "/index.html", "/about.html", "/notes.txt", "/logo.png", "/large.txt", "/missing.html"];

/* ---------------------------------------------------------------- API */
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try { res = await fetch(path, opts); } catch { throw new Error("The UI server (ui.py) is not responding. Is it still running?"); }
  let data;
  try { data = await res.json(); } catch { throw new Error(`ui.py returned ${res.status} without JSON.`); }
  if (!res.ok || data.ok === false) { const e = new Error(data.error || `HTTP ${res.status}`); e.data = data; e.status = res.status; throw e; }
  return data;
}

/* ---------------------------------------------------------------- formatting */
const fmtMs = (v) => v == null ? "—" : v >= 100 ? `${v.toFixed(0)} ms` : v >= 10 ? `${v.toFixed(1)} ms` : `${v.toFixed(2)} ms`;
const fmtBytes = (n) => n == null ? "—" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`;
const cacheBadge = (c) => c === "HIT" ? '<span class="badge hit">HIT</span>' : c === "MISS" ? '<span class="badge miss">MISS</span>' : '<span class="muted">—</span>';
const statusClass = (s) => s == null ? "bad" : s < 300 ? "ok" : s < 500 ? "warn" : "bad";

/* ---------------------------------------------------------------- router */
const PAGES = ["overview", "request", "inspector", "bench", "faults", "evidence", "config"];
function route() {
  const page = PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  $$(".page").forEach((p) => (p.hidden = p.dataset.page !== page));
  $$("[data-nav]").forEach((a) => (a.dataset.nav === page ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  document.title = `${$(`[data-nav="${page}"]`).textContent.trim()} · CacheNet Lab`;
  closeRail();
  if (page === "overview") { drawTopology(); refreshStats(); }
  if (page === "inspector") renderInspector();
  if (page === "bench") loadDatasets();
}
function closeRail() { $("#rail").classList.remove("open"); $("#menu-btn").setAttribute("aria-expanded", "false"); }

/* ---------------------------------------------------------------- reachability */
async function checkHealth(manual) {
  const btn = $("#refresh-btn");
  if (manual) { btn.classList.remove("spin"); void btn.offsetWidth; btn.classList.add("spin"); }
  try {
    const h = await api("/api/health");
    state.health = h;
    for (const k of ["proxy", "origin"]) {
      const el = $(`#reach-${k}`); const d = h.detail[k];
      el.dataset.state = d.reachable ? "up" : "down";
      el.querySelector("span").textContent = d.reachable ? "TCP reachable" : "Unreachable";
      el.title = `${d.host}:${d.port} · ${d.reachable ? `connect ${d.ms} ms` : d.error || "no answer"} · checked ${h.checked}`;
    }
  } catch (e) {
    for (const k of ["proxy", "origin"]) { const el = $(`#reach-${k}`); el.dataset.state = "unknown"; el.querySelector("span").textContent = "Unknown"; el.title = e.message; }
  }
  if (location.hash === "" || location.hash === "#overview") drawTopology();
}

/* ---------------------------------------------------------------- topology */
let topoLayout = null;
let lastTrace = null;

function el(tag, attrs = {}, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}

function drawTopology() {
  const host = $("#topology");
  if (!host || !state.config) return;
  const vertical = host.clientWidth < 640;
  const cfg = state.config;
  const W = vertical ? 360 : 1000, H = vertical ? 700 : 290;
  const box = vertical
    ? { c: [20, 20, 320, 170], p: [20, 265, 320, 170], o: [20, 510, 320, 170] }
    : { c: [0, 34, 262, 210], p: [369, 34, 262, 210], o: [738, 34, 262, 210] };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
  const links = {};
  const mid = (b) => [b[0] + b[2] / 2, b[1] + b[3] / 2];
  const linkPath = (a, b) => vertical
    ? `M ${mid(a)[0]} ${a[1] + a[3]} L ${mid(b)[0]} ${b[1]}`
    : `M ${a[0] + a[2]} ${mid(a)[1]} L ${b[0]} ${mid(b)[1]}`;
  const health = state.health?.detail || {};
  [["cp", box.c, box.p, cfg.proxy.port, health.proxy], ["po", box.p, box.o, cfg.origin.port, health.origin]].forEach(([id, a, b, port, h]) => {
    const g = el("g");
    const d = linkPath(a, b);
    const path = el("path", { d, class: "t-link" + (h && !h.reachable ? " fail" : ""), id: `link-${id}` });
    g.append(path);
    if (vertical) {
      const x = mid(a)[0] + 12, y = (a[1] + a[3] + b[1]) / 2;
      g.append(el("text", { x, y: y - 4, class: "t-link-proto" }, "CNTP/1.0"), el("text", { x, y: y + 12, class: "t-link-label" }, `TCP :${port}`));
    } else {
      const x = (a[0] + a[2] + b[0]) / 2, y = mid(a)[1];
      g.append(el("text", { x, y: y - 12, class: "t-link-proto", "text-anchor": "middle" }, "CNTP/1.0"), el("text", { x, y: y + 22, class: "t-link-label", "text-anchor": "middle" }, `TCP :${port}`));
    }
    links[id] = path;
    svg.append(g);
  });

  const node = (key, b, title, tag, addr) => {
    const g = el("g", { class: "t-node", id: `node-${key}`, "data-state": "idle" });
    g.append(el("rect", { x: b[0], y: b[1], width: b[2], height: b[3], rx: 10, class: "t-host" }));
    g.append(el("text", { x: b[0] + 16, y: b[1] + 26, class: "t-title" }, title));
    g.append(el("text", { x: b[0] + b[2] - 16, y: b[1] + 26, class: "t-tag", "text-anchor": "end" }, tag));
    g.append(el("text", { x: b[0] + 16, y: b[1] + 46, class: "t-addr" }, addr));
    g.append(el("text", { x: b[0] + b[2] - 16, y: b[1] + 46, class: "t-state", "text-anchor": "end", id: `state-${key}` }, ""));
    svg.append(g);
    return g;
  };
  const inner = (g, b, y, h) => g.append(el("rect", { x: b[0] + 14, y: b[1] + y, width: b[2] - 28, height: h, rx: 7, class: "t-inner" }));

  // Client host H3: browser and ui.py live here; the browser leg is local HTTP, not CNTP.
  const c = node("c", box.c, "Client", "H3", state.hc?.hosts?.h3 || "this machine");
  inner(c, box.c, 60, vertical ? 92 : 132);
  const cx = box.c[0] + 28, cy = box.c[1] + 60;
  c.append(el("text", { x: cx, y: cy + 22, class: "t-small-mono" }, "Browser"));
  c.append(el("text", { x: cx, y: cy + 38, class: "t-small" }, "HTTP · localhost:3000"));
  c.append(el("path", { d: `M ${cx + 110} ${cy + 17} H ${cx + 140}`, class: "t-local" }));
  c.append(el("text", { x: cx + 148, y: cy + 22, class: "t-small-mono" }, "ui.py"));
  c.append(el("text", { x: cx + 148, y: cy + 38, class: "t-small" }, "CNTP socket"));
  if (!vertical) {
    c.append(el("text", { x: cx, y: cy + 74, class: "t-small" }, "The browser cannot open raw TCP sockets,"));
    c.append(el("text", { x: cx, y: cy + 90, class: "t-small" }, "so ui.py speaks CNTP on its behalf."));
    c.append(el("text", { x: cx, y: cy + 114, class: "t-small-mono" }, `→ ${cfg.proxy.host}:${cfg.proxy.port}`));
  } else {
    c.append(el("text", { x: cx, y: cy + 68, class: "t-small-mono" }, `→ ${cfg.proxy.host}:${cfg.proxy.port}`));
  }

  // Proxy host H2 with the cache nested inside it.
  const p = node("p", box.p, "Caching proxy", "H2", `${cfg.proxy.host}:${cfg.proxy.port}`);
  inner(p, box.p, 60, vertical ? 92 : 132);
  const cache = el("g", { class: "t-cache", id: "t-cache", "data-state": "idle" });
  const kx = box.p[0] + 30, ky = box.p[1] + (vertical ? 78 : 84);
  cache.append(el("path", { d: `M ${kx} ${ky + 6} v 30 a 20 6 0 0 0 40 0 v -30`, class: "t-cyl" }));
  cache.append(el("ellipse", { cx: kx + 20, cy: ky + 6, rx: 20, ry: 6, class: "t-cyl" }));
  cache.append(el("path", { d: `M ${kx} ${ky + 20} a 20 6 0 0 0 40 0`, class: "t-cyl", fill: "none" }));
  p.append(cache);
  p.append(el("text", { x: kx + 54, y: ky + 12, class: "t-small-mono" }, "In-memory cache"));
  p.append(el("text", { x: kx + 54, y: ky + 30, class: "t-small", id: "t-cache-count" }, cacheCountText()));
  if (!vertical) {
    p.append(el("text", { x: kx - 2, y: ky + 70, class: "t-small" }, "Fresh copy: answer here (HIT)."));
    p.append(el("text", { x: kx - 2, y: ky + 86, class: "t-small" }, "Missing or expired: ask the origin (MISS)."));
  }

  // Origin host H1.
  const o = node("o", box.o, "Origin server", "H1", `${cfg.origin.host}:${cfg.origin.port}`);
  inner(o, box.o, 60, vertical ? 92 : 132);
  const ox = box.o[0] + 28, oy = box.o[1] + 60;
  o.append(el("text", { x: ox, y: oy + 22, class: "t-small-mono" }, "www/  document root"));
  o.append(el("text", { x: ox, y: oy + 40, class: "t-small" }, "Sets Max-Age on every 200 OK"));
  if (!vertical) {
    o.append(el("text", { x: ox, y: oy + 74, class: "t-small" }, "Contacted only on a MISS."));
    o.append(el("text", { x: ox, y: oy + 90, class: "t-small" }, "PURGE and HITs never reach it."));
  }

  if (!state.history.length) {
    svg.append(el("text", { x: W / 2, y: vertical ? H - 4 : H - 2, class: "t-prompt", "text-anchor": "middle" }, "Send a request to trace its route"));
  }
  host.replaceChildren(svg);
  topoLayout = { svg, links, vertical };
  if (lastTrace) applyTraceFinal(lastTrace);
}

function cacheCountText() {
  const s = state.stats;
  if (!s) return "reading…";
  if (!s.supported) return "STATS not supported";
  return `${s.entry_count} cached object${s.entry_count === 1 ? "" : "s"}`;
}

function hopsFor(r) {
  if (r.unreachable) return [["cp", "fail"]];
  if (r.cache === "HIT") return [["cp"], ["pc"]];
  if (r.cache === "MISS") {
    if (r.status === 502 || r.status === 504) return [["cp"], ["po", "fail"], ["pc"]];
    return [["cp"], ["po"], ["op"], ["pc"]];
  }
  return [["cp"], ["pc"]]; // PURGE and proxy-local errors (400, 405, 505) never leave H2
}

function setNode(key, st, label, cls) {
  const g = $(`#node-${key}`); if (g) g.dataset.state = st;
  const t = $(`#state-${key}`); if (t) { t.textContent = label || ""; t.setAttribute("class", "t-state " + (cls || "")); }
}

function applyTraceFinal(r) {
  const hops = hopsFor(r);
  const touched = new Set(hops.map((h) => h[0].replace("op", "po").replace("pc", "cp")));
  $$(".t-link").forEach((l) => l.classList.remove("lit", "dim"));
  const cp = $("#link-cp"), po = $("#link-po");
  if (cp) cp.classList.add(touched.has("cp") ? "lit" : "dim");
  if (po) { po.classList.add(hops.some((h) => h[0] === "po") ? "lit" : "dim"); if (hops.some((h) => h[1] === "fail" && h[0] === "po")) po.classList.add("fail"); }
  const cache = $("#t-cache");
  const err = r.status == null || r.status >= 400;
  setNode("c", "active", r.status ? `${r.status}` : "NO ANSWER", err ? "error" : "active");
  if (r.unreachable) { setNode("p", "error", "UNREACHABLE", "error"); setNode("o", "dim"); return; }
  if (r.method === "PURGE") { setNode("p", "active", r.status === 200 ? "PURGED" : "NOT CACHED", "active"); setNode("o", "dim"); if (cache) cache.dataset.state = "purge"; return; }
  if (r.cache === "HIT") { setNode("p", "hit", "HIT", "hit"); setNode("o", "dim", ""); if (cache) cache.dataset.state = "hit"; return; }
  if (r.cache === "MISS") {
    if (cache) cache.dataset.state = "miss";
    if (r.status === 502 || r.status === 504) { setNode("p", "error", `MISS · ${r.status}`, "error"); setNode("o", "error", "NO VALID ANSWER", "error"); return; }
    setNode("p", "miss", "MISS · FORWARD", "miss"); setNode("o", "active", `${r.status}`, err ? "error" : "active"); return;
  }
  setNode("p", err ? "error" : "active", `${r.status ?? ""} LOCAL`, err ? "error" : "active"); setNode("o", "dim");
}

function replay(r) {
  lastTrace = r;
  if (!topoLayout || $("#topology").offsetParent === null || reduceMotion()) { if (topoLayout) applyTraceFinal(r); return; }
  ["c", "p", "o"].forEach((k) => setNode(k, "idle", ""));
  $$(".t-link").forEach((l) => l.classList.remove("lit", "dim", "fail"));
  const cache = $("#t-cache"); if (cache) cache.dataset.state = "idle";
  setNode("c", "active", "SEND", "active");
  const hops = hopsFor(r);
  const per = Math.min(260, 900 / hops.length);
  const svg = topoLayout.svg;
  let i = 0;
  const step = () => {
    if (i >= hops.length) { applyTraceFinal(r); return; }
    const [id, flag] = hops[i++];
    const back = id === "op" || id === "pc";
    const path = $(`#link-${back ? id.split("").reverse().join("") : id}`);
    if (!path) { step(); return; }
    path.classList.add("lit");
    if (id === "cp") setNode("p", "active", "LOOKUP", "active");
    if (id === "po") setNode("o", "active", "REQUEST", "active");
    const len = path.getTotalLength();
    const dot = el("circle", { r: 5, class: "t-packet" + (back ? " back" : "") });
    svg.append(dot);
    const t0 = performance.now();
    const failAt = flag === "fail" ? 0.82 : 1;
    const frame = (now) => {
      let t = Math.min(1, (now - t0) / per);
      const e = 1 - Math.pow(1 - t, 3);
      const pos = path.getPointAtLength(len * (back ? 1 - e * failAt : e * failAt));
      dot.setAttribute("cx", pos.x); dot.setAttribute("cy", pos.y);
      if (t < 1) { requestAnimationFrame(frame); return; }
      dot.remove();
      if (flag === "fail") {
        path.classList.add("fail");
        const x = el("g"); [[-5, -5, 5, 5], [-5, 5, 5, -5]].forEach(([a, b, c2, d]) => x.append(el("line", { x1: pos.x + a, y1: pos.y + b, x2: pos.x + c2, y2: pos.y + d, class: "t-x" })));
        svg.append(x); setTimeout(() => x.remove(), 1400);
      }
      if (id === "cp" && r.cache === "HIT") { if (cache) cache.dataset.state = "hit"; setNode("p", "hit", "HIT", "hit"); setNode("o", "dim"); }
      if (id === "cp" && r.cache === "MISS") { if (cache) cache.dataset.state = "miss"; setNode("p", "miss", "MISS · FORWARD", "miss"); }
      if (id === "cp" && r.method === "PURGE" && cache) cache.dataset.state = "purge";
      step();
    };
    requestAnimationFrame(frame);
  };
  step();
}

/* ---------------------------------------------------------------- proxy stats */
let statsTimer = null;
async function refreshStats() {
  try { state.stats = await api("/api/stats"); state.statsAt = Date.now(); }
  catch (e) { state.stats = null; state.statsError = e.message; }
  renderStats();
  const t = $("#t-cache-count"); if (t) t.textContent = cacheCountText();
}
function renderStats() {
  const host = $("#stats-body");
  const s = state.stats;
  if (!s) { host.innerHTML = `<p class="empty">Could not read the proxy. ${esc(state.statsError || "")}</p>`; return; }
  if (!s.supported) { host.innerHTML = `<p class="empty">This proxy does not answer STATS (<code>${esc(s.status_line)}</code>). Update proxy.py on H2 to see global counters. Session counts on the left still work.</p>`; return; }
  const total = s.hits + s.misses;
  const ratio = total ? (s.hits / total) * 100 : 0;
  const age = (Date.now() - state.statsAt) / 1000;
  const entries = s.entries.map((e) => ({ ...e, left: Math.max(0, e.ttl - age) })).filter((e) => e.left > 0);
  host.innerHTML = `
    <div class="cache-counters">
      <div class="stat"><b class="hitc">${s.hits}</b><span>HITs (all clients)</span></div>
      <div class="stat"><b class="missc">${s.misses}</b><span>MISSes (all clients)</span></div>
      <div class="stat"><b>${fmtBytes(s.bytes_saved)}</b><span>Body bytes not fetched from origin</span></div>
      <div class="stat"><b>${total ? ratio.toFixed(1) + "%" : "—"}</b><span>Hit ratio</span></div>
      ${total ? `<div class="ratio"><div class="ratio-bar" role="img" aria-label="${s.hits} hits and ${s.misses} misses"><i class="h" style="width:${ratio}%"></i><i class="m" style="width:${100 - ratio}%"></i></div>
      <div class="ratio-legend"><span>HIT ${s.hits}</span><span>MISS ${s.misses}</span></div></div>` : ""}
    </div>
    <div class="entries-head"><span>Cached object</span><span>TTL left · body</span></div>
    ${entries.length ? `<ul class="entries">${entries.map((e) => `<li><span>${esc(e.path)}</span><span class="ttl ${e.left < 10 ? "low" : ""}">${Math.ceil(e.left)} s</span><span class="size">${fmtBytes(e.bytes)}</span></li>`).join("")}</ul>`
      : `<p class="empty">Cache is empty. The next GET of any object will be a MISS.</p>`}`;
}
setInterval(() => { if (state.stats?.supported && !$('[data-page="overview"]').hidden) renderStats(); }, 1000);

/* ---------------------------------------------------------------- sending requests */
async function send(method, path, mode, btn) {
  if (method === "PURGE" && path === "*") {
    const dlg = $("#confirm-dialog");
    const ok = await new Promise((res) => { dlg.returnValue = ""; dlg.showModal(); dlg.addEventListener("close", () => res(dlg.returnValue === "ok"), { once: true }); });
    if (!ok) return null;
  }
  btn?.classList.add("busy"); if (btn) btn.disabled = true;
  let r;
  try {
    r = await api("/api/request", { method, path, mode });
  } catch (e) {
    r = { method, path, mode, ok: false, error: e.message, unreachable: !!e.data?.unreachable, status: null, cache: null, time: new Date().toLocaleTimeString([], { hour12: false }) };
  } finally { btn?.classList.remove("busy"); if (btn) btn.disabled = false; }
  r.id = state.history.length + 1;
  state.history.unshift(r);
  state.selected = r.id;
  renderActivity(); renderLastOp(r); renderResult(r); replay(r); refreshStats();
  if (r.unreachable) checkHealth();
  return r;
}

function renderLastOp(r) {
  const op = $("#last-op");
  if (r.error) { op.innerHTML = `<span class="status-err">${esc(r.method)} ${esc(r.path)}: ${esc(r.error)}</span>`; return; }
  op.innerHTML = `<span class="op-ok">${esc(r.method)} ${esc(r.path)}</span> → ${esc(r.status_line?.replace(/^CNTP\/1\.0 /, "") || "")} ${r.cache ? "· " + cacheBadge(r.cache) : ""} · ${fmtMs(r.ms)}`;
}

function renderActivity() {
  const rows = state.history.slice(0, 12);
  $("#activity-empty").hidden = rows.length > 0;
  $("#activity tbody").innerHTML = rows.map((r) => `
    <tr class="clickable" tabindex="0" data-id="${r.id}" title="Open in the protocol inspector">
      <td class="mono">${esc(r.time)}</td><td class="mono">${esc(r.method)}</td><td class="mono">${esc(r.path)}</td>
      <td>${cacheBadge(r.cache)}</td>
      <td class="mono ${r.status && r.status < 400 ? "status-ok" : "status-err"}">${r.status ?? "failed"}</td>
      <td class="num">${r.error ? "—" : fmtMs(r.ms)}</td></tr>`).join("");
  const done = state.history.filter((r) => !r.error);
  const hits = done.filter((r) => r.cache === "HIT").length, misses = done.filter((r) => r.cache === "MISS").length;
  const timed = done.filter((r) => r.method !== "PURGE");
  const mean = timed.length ? timed.reduce((a, r) => a + r.ms, 0) / timed.length : null;
  $("#session-stats").innerHTML = `
    <div class="stat"><b>${state.history.length}</b><span>Requests</span></div>
    <div class="stat"><b class="hitc">${hits}</b><span>HIT</span></div>
    <div class="stat"><b class="missc">${misses}</b><span>MISS</span></div>
    <div class="stat"><b>${mean == null ? "—" : fmtMs(mean)}</b><span>Mean GET/HEAD time</span></div>`;
}

/* ---------------------------------------------------------------- request lab */
function renderResult(r) {
  $("#lab-empty").hidden = true; $("#lab-out").hidden = false;
  const code = $("#r-code");
  if (r.error) {
    code.textContent = "—"; code.className = "status-code bad";
    $("#r-line").textContent = "No CNTP response";
    $("#r-cache").outerHTML = '<span class="badge err" id="r-cache">FAILED</span>';
    $("#r-facts").innerHTML = `<div style="grid-column:1/-1"><dt>What happened</dt><dd>${esc(r.error)}</dd></div>
      ${r.unreachable ? `<div style="grid-column:1/-1"><dt>Fix</dt><dd>Start the proxy on H2: <code>python proxy.py --origin-host &lt;H1-IP&gt;</code>, then check the firewall allows TCP ${state.config?.proxy.port}.</dd></div>` : ""}`;
    $("#r-body").innerHTML = ""; $("#r-headers").innerHTML = ""; return;
  }
  code.textContent = r.status ?? "—"; code.className = "status-code " + statusClass(r.status);
  $("#r-line").textContent = r.status_line;
  const badgeHtml = r.cache === "HIT" ? '<span class="badge hit" id="r-cache">HIT · served by H2</span>' : r.cache === "MISS" ? '<span class="badge miss" id="r-cache">MISS · fetched from H1</span>' : `<span class="badge none" id="r-cache">${r.method === "PURGE" ? "Cache management" : "Answered by proxy"}</span>`;
  $("#r-cache").outerHTML = badgeHtml;
  const conn = r.mode === "keep-alive" ? `#${r.conn_id} · request ${r.conn_requests} ${r.reused ? "(reused)" : "(new)"}` : `#${r.conn_id} · closed after response`;
  const facts = [
    ["Total time", `${fmtMs(r.ms)}`],
    ["TCP connect", r.reused ? "0 ms <small>(reused)</small>" : fmtMs(r.connect_ms)],
    ["Request → full response", fmtMs(r.transfer_ms)],
    ["Content-Type", esc(r.content_type || "—")],
    ["Body", r.method === "HEAD" ? "none (HEAD)" : `${fmtBytes(r.body_bytes)}`],
    ["Max-Age", r.max_age ? `${esc(r.max_age)} s` : "not sent"],
    ["Connection", esc(conn)],
    ["Bytes on the wire (app)", `${r.request_bytes} out · ${r.response_bytes} in`],
  ];
  $("#r-facts").innerHTML = facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  $("#r-headers").innerHTML = `<table class="data fieldtable"><tbody>${r.header_list.map(([n, v]) => `<tr><td class="mono">${esc(n)}</td><td class="mono">${esc(v)}</td></tr>`).join("")}</tbody></table>`;
  const body = $("#r-body");
  if (r.method === "HEAD" || r.body_bytes === 0) { body.innerHTML = `<p class="empty">${r.method === "HEAD" ? "No response body. HEAD returns headers only." : "Empty body."}</p>`; return; }
  const ct = r.content_type || "";
  if (ct.startsWith("image/") && r.body_encoding === "base64") {
    body.innerHTML = `<div class="body-tools"><span class="muted small mono">${esc(ct)} · ${fmtBytes(r.body_bytes)}</span></div><div class="img-preview"><img alt="${esc(r.path)} as returned by the proxy" src="data:${esc(ct)};base64,${r.body}"></div>`;
  } else if (ct.startsWith("text/html")) {
    body.innerHTML = `<div class="body-tools"><div class="seg" role="radiogroup" aria-label="HTML view"><label><input type="radio" name="hv" value="preview" checked><span>Preview</span></label><label><input type="radio" name="hv" value="source"><span>Source</span></label></div><span class="muted small mono">${fmtBytes(r.body_bytes)} · sandboxed, scripts off</span></div><iframe class="preview-frame" sandbox="" title="HTML preview"></iframe><pre class="viewer" hidden></pre>`;
    $("iframe", body).srcdoc = r.body; $("pre", body).textContent = r.body;
    $$('input[name="hv"]', body).forEach((i) => i.addEventListener("change", () => {
      const src = $('input[name="hv"]:checked', body).value === "source";
      $("iframe", body).hidden = src; $("pre", body).hidden = !src;
    }));
  } else if (r.body_encoding === "text") {
    const big = r.body.length > 60000;
    body.innerHTML = `<div class="body-tools"><span class="muted small mono">${esc(ct || "text")} · ${fmtBytes(r.body_bytes)}${big ? " · first 60,000 characters shown" : ""}</span><label class="muted small"><input type="checkbox" id="wrap-toggle" checked> Wrap lines</label></div><pre class="viewer"></pre>`;
    $("pre", body).textContent = big ? r.body.slice(0, 60000) : r.body;
    $("#wrap-toggle").addEventListener("change", (e) => $("pre", body).classList.toggle("nowrap", !e.target.checked));
  } else {
    body.innerHTML = `<p class="empty">Binary body: ${esc(ct || "unknown type")}, ${fmtBytes(r.body_bytes)}. Not decoded as text.</p>`;
  }
}

function setupRequestLab() {
  const input = $("#lab-path"), err = $("#lab-path-err");
  const chips = $("#path-chips");
  const paintChips = () => {
    const m = $('input[name="lm"]:checked').value;
    chips.innerHTML = [...RESOURCES, ...(m === "PURGE" ? ["*"] : [])].map((p) => `<button type="button" class="chip-btn" aria-pressed="${input.value === p}" data-p="${esc(p)}">${esc(p === "*" ? "* (all)" : p)}</button>`).join("");
  };
  chips.addEventListener("click", (e) => { const b = e.target.closest("[data-p]"); if (!b) return; input.value = b.dataset.p; validate(); paintChips(); });
  const validate = () => {
    const v = input.value.trim(); const m = $('input[name="lm"]:checked').value;
    let msg = "";
    if (!v) msg = "Enter a path, for example /index.html.";
    else if (v === "*" && m !== "PURGE") msg = "* means the whole cache and only works with PURGE.";
    else if (v !== "*" && !v.startsWith("/")) msg = "Paths start with /, for example /about.html.";
    else if (/\s/.test(v)) msg = "Paths cannot contain spaces: the request line is METHOD PATH VERSION.";
    err.textContent = msg; input.setAttribute("aria-invalid", msg ? "true" : "false");
    return !msg;
  };
  input.addEventListener("input", () => { validate(); paintChips(); });
  $$('input[name="lm"]').forEach((i) => i.addEventListener("change", () => { validate(); paintChips(); }));
  const modeHint = () => {
    const keep = $('input[name="cm"]:checked').value === "keep-alive";
    $("#mode-hint").textContent = keep
      ? "ui.py keeps one TCP connection to the proxy open and reuses it. The proxy closes it after 15 s idle; the next request then opens a new one."
      : "A new TCP connection for every request (handshake each time), closed after the response.";
  };
  $$('input[name="cm"]').forEach((i) => i.addEventListener("change", modeHint)); modeHint();
  paintChips();
  $("#lab-form").addEventListener("submit", (e) => {
    e.preventDefault(); if (!validate()) { input.focus(); return; }
    send($('input[name="lm"]:checked').value, input.value.trim(), $('input[name="cm"]:checked').value, $("#lab-send"));
  });
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    $$(".tab-panel").forEach((p) => (p.hidden = p.dataset.panel !== b.dataset.tab));
  }));
  $("#quick-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const m = $('input[name="qm"]:checked').value; let p = $("#quick-path").value;
    if (p === "*" && m !== "PURGE") { $("#last-op").innerHTML = '<span class="status-err">* only works with PURGE. Pick PURGE or another resource.</span>'; return; }
    send(m, p, "close", $("#quick-send"));
  });
}

/* ---------------------------------------------------------------- inspector */
function wireLines(raw, isResp, bodyText, bodyBytes, method) {
  const head = raw.split("\r\n\r\n")[0];
  const lines = head.split("\r\n");
  let n = 0;
  const out = lines.map((l, i) => {
    n++;
    if (i === 0) return `<div class="ln"><span class="no">${n}</span><span class="start">${esc(l)}</span><span class="crlf">CRLF</span></div>`;
    const k = l.indexOf(":");
    const name = l.slice(0, k), value = l.slice(k + 1);
    const vcls = name.toLowerCase() === "x-cache" ? (value.trim() === "HIT" ? "xc-hit" : "xc-miss") : "hv";
    return `<div class="ln"><span class="no">${n}</span><span class="hn">${esc(name)}</span>:<span class="${vcls}">${esc(value)}</span><span class="crlf">CRLF</span></div>`;
  });
  n++;
  out.push(`<div class="ln sep"><span class="no">${n}</span><span class="crlf">CRLF</span><span class="muted small" style="margin-left:10px">blank line: end of headers</span></div>`);
  if (isResp) {
    if (method === "HEAD") out.push(`<div class="ln"><span class="no"></span><span class="bodynote">no body (HEAD); Content-Length describes the GET body</span></div>`);
    else if (bodyBytes) {
      const preview = bodyText != null ? bodyText.slice(0, 600) : null;
      out.push(`<div class="ln"><span class="no"></span><span class="bodyln">${preview != null ? esc(preview) : ""}</span></div>`);
      out.push(`<div class="ln"><span class="no"></span><span class="bodynote">${preview == null ? `${bodyBytes} bytes of binary body` : bodyText.length > 600 ? `… ${bodyBytes} body bytes in total` : `${bodyBytes} body bytes`}</span></div>`);
    }
  }
  return `<div class="wire">${out.join("")}</div>`;
}

function renderInspector() {
  const sel = $("#insp-select");
  const done = state.history.filter((r) => !r.error);
  $("#insp-empty").hidden = done.length > 0; $("#insp-grid").hidden = done.length === 0;
  sel.disabled = !done.length;
  sel.innerHTML = done.map((r) => `<option value="${r.id}">#${r.id} ${esc(r.time)}  ${esc(r.method)} ${esc(r.path)}  → ${r.status}${r.cache ? " " + r.cache : ""}</option>`).join("");
  if (!done.length) return;
  const cur = done.find((r) => r.id === state.selected) || done[0];
  sel.value = cur.id;
  const parsed = $('input[name="iv"]:checked').value === "parsed";
  $("#insp-req-bytes").textContent = `${cur.request_bytes} bytes`;
  $("#insp-res-bytes").textContent = `${cur.response_bytes} bytes`;
  if (!parsed) {
    $("#insp-req").innerHTML = wireLines(cur.request_raw, false);
    $("#insp-res").innerHTML = wireLines(cur.response_head_raw, true, cur.body_encoding === "text" ? cur.body : null, cur.body_bytes, cur.method);
    return;
  }
  const reqLines = cur.request_raw.split("\r\n");
  const [m, p, v] = reqLines[0].split(" ");
  const reqHeaders = reqLines.slice(1).filter(Boolean).map((l) => [l.slice(0, l.indexOf(":")), l.slice(l.indexOf(":") + 1).trim()]);
  const table = (rows) => `<table class="data fieldtable"><tbody>${rows.map(([a, b]) => `<tr><td>${a}</td><td class="mono">${b}</td></tr>`).join("")}</tbody></table>`;
  $("#insp-req").innerHTML = `<h3>Start line</h3>${table([["Method", esc(m)], ["Resource", esc(p)], ["Protocol version", `<span style="color:var(--proto)">${esc(v)}</span>`]])}
    <h3>Headers</h3>${table(reqHeaders.map(([a, b]) => [esc(a), esc(b)]))}
    <div class="framing"><div class="row"><span>Header block</span><span>${cur.request_bytes} bytes, ends with CRLF CRLF</span></div><div class="row"><span>Body</span><span>none (no Content-Length)</span></div><div class="row"><span>Connection mode</span><span>${cur.mode === "keep-alive" ? "keep-alive" : "close after response"}</span></div></div>`;
  const headBytes = new TextEncoder().encode(cur.response_head_raw).length;
  const cl = cur.content_length != null ? Number(cur.content_length) : null;
  const framingOk = cur.method === "HEAD" ? true : cl === cur.body_bytes;
  const [ver, code, ...reason] = cur.status_line.split(" ");
  $("#insp-res").innerHTML = `<h3>Status line</h3>${table([["Protocol version", `<span style="color:var(--proto)">${esc(ver)}</span>`], ["Status code", esc(code)], ["Reason phrase", esc(reason.join(" "))]])}
    <h3>Headers</h3>${table(cur.header_list.map(([a, b]) => [esc(a), esc(b)]))}
    <h3>Cache metadata</h3>${table([["X-Cache", cur.cache ? cacheBadge(cur.cache) : "absent (proxy answered itself)"], ["Max-Age", cur.max_age ? `${esc(cur.max_age)} s (set by origin)` : "absent"]])}
    <div class="framing">
      <div class="row"><span>Header block incl. CRLF CRLF</span><span>${headBytes} bytes</span></div>
      <div class="row"><span>Content-Length header</span><span>${cl ?? "absent"}</span></div>
      <div class="row"><span>Body bytes read</span><span>${cur.method === "HEAD" ? "0 (HEAD)" : cur.body_bytes}</span></div>
      <div class="row"><span>Framing</span><span class="${framingOk ? "okline" : "badline"}">${framingOk ? "body length matches Content-Length" : "mismatch"}</span></div>
    </div>`;
}

/* ---------------------------------------------------------------- benchmarks */
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
const CHARTS = [
  { title: "Small object: MISS vs HIT", sub: "/index.html · new TCP connection per request", unit: "ms", rows: [["Object /index.html", "MISS", "MISS"], ["Object /index.html", "HIT", "HIT"]] },
  { title: "Large object transfer time", sub: "/large.txt (~200 KB)", unit: "ms", rows: [["Throughput /large.txt", "MISS", "MISS"], ["Throughput /large.txt", "HIT", "HIT"]] },
  { title: "Application throughput", sub: "/large.txt · response bytes × 8 / transfer time", unit: "Mbps", mbps: true, rows: [["Throughput /large.txt", "MISS", "MISS"], ["Throughput /large.txt", "HIT", "HIT"]] },
  { title: "Page fetch, 4 objects", sub: "keep-alive vs close after response", unit: "ms", rows: [["Page fetch (4 objects)", "persistent, warm cache", "Keep-alive|warm"], ["Page fetch (4 objects)", "non-persistent, warm cache", "Close|warm"], ["Page fetch (4 objects)", "persistent, cold cache", "Keep-alive|cold"], ["Page fetch (4 objects)", "non-persistent, cold cache", "Close|cold"]] },
  { title: "Round-trip time to the proxy", sub: "TCP handshake vs CNTP HEAD on an open connection", unit: "ms", rows: [["TCP connect (~1 RTT)", "client->proxy", "TCP connect"], ["App RTT (HEAD, open conn)", "cached", "HEAD on open conn"]] },
];
const summarize = (v) => { const n = v.length, mean = v.reduce((a, b) => a + b, 0) / n; const s = [...v].sort((a, b) => a - b); const med = n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; const sd = n > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0; return { n, mean, med, sd, min: s[0], max: s[n - 1] }; };
const cellValues = (cell, mbps) => mbps ? cell.ms.map((ms, i) => (cell.bytes[i] * 8) / (ms / 1000) / 1e6) : cell.ms;

async function loadDatasets() {
  try {
    const { datasets } = await api("/api/benchmark/results");
    state.datasets = datasets;
    if (!state.chosen) {
      const saved = store.get("datasets", null);
      const newestPerLabel = []; const seen = new Set();
      for (const d of datasets) if (!seen.has(d.label)) { seen.add(d.label); newestPerLabel.push(d.id); }
      state.chosen = (saved || newestPerLabel).filter((id) => datasets.some((d) => d.id === id)).slice(0, 4);
    }
    renderDatasetPicker(); await loadResults();
  } catch (e) { $("#datasets").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function renderDatasetPicker() {
  const host = $("#datasets");
  if (!state.datasets.length) { host.innerHTML = '<p class="empty">No bench.py results yet. Run the formal suite above, or copy bench_*_raw.csv files into results/.</p>'; return; }
  host.innerHTML = state.datasets.map((d) => {
    const idx = state.chosen.indexOf(d.id);
    return `<label class="ds"><input type="checkbox" value="${esc(d.id)}" ${idx >= 0 ? "checked" : ""} ${idx < 0 && state.chosen.length >= 4 ? "disabled" : ""}>${idx >= 0 ? `<i class="sw" style="background:${SERIES[idx]}"></i>` : ""}<b>${esc(d.label)}</b><time>${esc(d.stamp)}</time></label>`;
  }).join("");
  $$("input", host).forEach((i) => i.addEventListener("change", () => {
    state.chosen = i.checked ? [...state.chosen, i.value] : state.chosen.filter((x) => x !== i.value);
    store.set("datasets", state.chosen); renderDatasetPicker(); loadResults();
  }));
}
async function loadResults() {
  const charts = $("#charts"), table = $("#bench-table");
  if (!state.chosen.length) { charts.innerHTML = ""; table.innerHTML = ""; return; }
  try {
    const { datasets } = await api("/api/benchmark/results?ids=" + encodeURIComponent(state.chosen.join(",")));
    state.results = datasets.sort((a, b) => state.chosen.indexOf(a.id) - state.chosen.indexOf(b.id));
    charts.innerHTML = CHARTS.map((c, i) => `<figure class="chart" id="chart-${i}" style="margin:0"><h3>${c.title}</h3><p class="sub">${c.sub}</p></figure>`).join("");
    CHARTS.forEach((c, i) => drawChart($(`#chart-${i}`), c, state.results));
    renderBenchTable();
  } catch (e) { charts.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

function niceMax(v) { const p = Math.pow(10, Math.floor(Math.log10(v || 1))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p; return 10 * p; }

function drawChart(fig, spec, sets) {
  const W = 520, H = 250, L = 46, R = 10, T = 16, B = 44;
  const groups = spec.rows.map(([test, cond, label]) => ({ label, cells: sets.map((s, si) => { const cell = s.tests.find((t) => t.test === test && t.condition === cond); return cell ? { si, set: s, vals: cellValues(cell, spec.mbps), xc: cell.x_cache } : null; }) }));
  let maxV = 0; groups.forEach((g) => g.cells.forEach((c) => { if (c) { const s = summarize(c.vals); maxV = Math.max(maxV, s.max, s.mean + s.sd); } }));
  if (!maxV) { fig.insertAdjacentHTML("beforeend", '<p class="empty">Not in the selected datasets.</p>'); return; }
  const top = niceMax(maxV * 1.08);
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${spec.title}, ${spec.unit}` });
  for (let i = 0; i <= 4; i++) {
    const v = (top / 4) * i, yy = y(v);
    svg.append(el("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "c-grid" }));
    svg.append(el("text", { x: L - 8, y: yy + 3.5, class: "c-axis", "text-anchor": "end" }, v >= 100 ? v.toFixed(0) : +v.toFixed(1)));
  }
  svg.append(el("text", { x: 6, y: T - 4, class: "c-axis" }, spec.unit));
  const gw = (W - L - R) / groups.length, n = sets.length, bw = Math.min(44, (gw * 0.7) / n);
  groups.forEach((g, gi) => {
    const gx = L + gw * gi + gw / 2;
    g.label.split("|").forEach((part, li) => svg.append(el("text", { x: gx, y: H - B + 18 + li * 14, class: "c-cat", "text-anchor": "middle" }, part)));
    g.cells.forEach((c, ci) => {
      if (!c) return;
      const s = summarize(c.vals);
      const x = gx - (n * bw) / 2 + ci * bw + 1;
      const w = bw - 2, y0 = y(0), ym = y(s.mean), r = Math.min(4, w / 2, y0 - ym);
      svg.append(el("path", { d: `M ${x} ${y0} V ${ym + r} Q ${x} ${ym} ${x + r} ${ym} H ${x + w - r} Q ${x + w} ${ym} ${x + w} ${ym + r} V ${y0} Z`, fill: SERIES[c.si], class: "c-bar" }));
      const cx = x + w / 2;
      if (s.sd > 0) { svg.append(el("line", { x1: cx, x2: cx, y1: y(Math.max(0, s.mean - s.sd)), y2: y(s.mean + s.sd), class: "c-err" })); [s.mean - s.sd, s.mean + s.sd].forEach((v) => svg.append(el("line", { x1: cx - 4, x2: cx + 4, y1: y(Math.max(0, v)), y2: y(Math.max(0, v)), class: "c-err" }))); }
      c.vals.forEach((v, k) => svg.append(el("circle", { cx: cx + (c.vals.length > 1 ? ((k / (c.vals.length - 1)) - 0.5) * Math.min(10, w - 8) : 0), cy: y(v), r: 2.6, class: "c-dot" })));
      svg.append(el("text", { x: cx, y: y(Math.max(s.mean + s.sd, s.max)) - 6, class: "c-val", "text-anchor": "middle" }, s.mean >= 100 ? s.mean.toFixed(0) : s.mean.toFixed(1)));
      const hit = el("rect", { x: x - 1, y: T, width: w + 2, height: H - T - B, class: "c-hit", tabindex: "0", role: "img", "aria-label": `${c.set.label} ${g.label.replace("|", " ")}: mean ${s.mean.toFixed(2)} ${spec.unit}` });
      const tip = `<b>${esc(c.set.label)}</b> · ${esc(g.label.replace("|", ", "))}<br>mean <b>${s.mean.toFixed(2)}</b> · median <b>${s.med.toFixed(2)}</b> ${spec.unit}<br><span class="t-sub">±${s.sd.toFixed(2)} sd · min ${s.min.toFixed(2)} · max ${s.max.toFixed(2)} · n=${s.n}</span>`;
      const show = (ev) => showTip(tip, ev, hit);
      hit.addEventListener("mousemove", show); hit.addEventListener("mouseleave", hideTip); hit.addEventListener("focus", show); hit.addEventListener("blur", hideTip);
      svg.append(hit);
    });
  });
  fig.append(svg);
  if (sets.length > 1) fig.insertAdjacentHTML("beforeend", `<div class="chart-legend">${sets.map((s, i) => `<span><i style="background:${SERIES[i]}"></i>${esc(s.label)}</span>`).join("")}</div>`);
}
function showTip(html, ev, target) {
  const t = $("#tooltip"); t.innerHTML = html; t.hidden = false;
  const r = ev && ev.clientX ? { x: ev.clientX, y: ev.clientY } : (() => { const b = target.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + 30 }; })();
  const tw = t.offsetWidth, th = t.offsetHeight;
  t.style.left = Math.min(window.innerWidth - tw - 8, Math.max(8, r.x + 14)) + "px";
  t.style.top = Math.max(8, r.y - th - 12) + "px";
}
function hideTip() { $("#tooltip").hidden = true; }

function renderBenchTable() {
  const rows = [];
  for (const s of state.results) for (const t of s.tests) {
    const st = summarize(t.ms); const big = t.bytes[0] > 1000;
    const mb = big ? summarize(cellValues(t, true)).mean : null;
    rows.push(`<tr><td>${esc(s.label)}</td><td>${esc(t.test)}</td><td>${esc(t.condition)}</td><td class="num">${st.n}</td><td class="num">${st.mean.toFixed(2)}</td><td class="num">${st.med.toFixed(2)}</td><td class="num">${st.sd.toFixed(2)}</td><td class="num">${st.min.toFixed(2)}</td><td class="num">${st.max.toFixed(2)}</td><td class="num">${t.bytes[0] ? fmtBytes(Math.round(t.bytes.reduce((a, b) => a + b, 0) / t.bytes.length)) : "—"}</td><td class="num">${mb == null ? "—" : mb.toFixed(2)}</td></tr>`);
  }
  $("#bench-table").innerHTML = `<caption class="chart-caption" style="text-align:left;caption-side:top">Bar = mean, error bar = ±1 standard deviation, dots = individual runs. Source: ${state.results.map((s) => `<code>${esc(s.id)}</code>`).join(", ")}</caption>
    <thead><tr><th>Dataset</th><th>Test</th><th>Condition</th><th class="num">Runs</th><th class="num">Mean ms</th><th class="num">Median ms</th><th class="num">Std dev</th><th class="num">Min</th><th class="num">Max</th><th class="num">Bytes</th><th class="num">Mbps</th></tr></thead><tbody>${rows.join("")}</tbody>`;
}

let formalTimer = null;
async function pollFormal() {
  const s = await api("/api/benchmark/formal").catch(() => null);
  if (!s) return;
  const log = $("#f-log"), btn = $("#f-start");
  if (s.state !== "idle") { log.hidden = false; log.textContent = [`$ bench.py --label ${s.label} --runs ${s.runs}   (started ${s.started})`, ...s.lines, s.state === "running" ? "running…" : `${s.state.toUpperCase()} at ${s.finished}`].join("\n"); log.scrollTop = log.scrollHeight; }
  btn.disabled = s.state === "running"; btn.classList.toggle("busy", s.state === "running");
  if (s.state === "running") { formalTimer = setTimeout(pollFormal, 800); return; }
  if (s.state === "completed" && formalTimer !== "done") { const raw = s.files.find((f) => f.endsWith("_raw.csv")); state.chosen = raw ? [raw, ...state.chosen.filter((x) => x !== raw)].slice(0, 4) : state.chosen; store.set("datasets", state.chosen); formalTimer = "done"; loadDatasets(); }
}
function setupBench() {
  $("#formal-form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("#f-err").textContent = "";
    const label = $("#f-label").value.trim(), runs = Number($("#f-runs").value);
    try { await api("/api/benchmark/formal", { label, runs }); formalTimer = null; pollFormal(); }
    catch (err) { $("#f-err").textContent = err.message; }
  });
  const quick = async (persistent, btn) => {
    btn.disabled = true; btn.classList.add("busy");
    try {
      const r = await api("/api/bench", { persistent });
      const id = persistent ? "quick-keep" : "quick-close";
      let card = $("#" + id);
      if (!card) { $("#quick-out").insertAdjacentHTML(persistent ? "beforeend" : "afterbegin", `<div class="quick-card" id="${id}"></div>`); card = $("#" + id); }
      const ms = r.rows.map((x) => Number(x.Response_Time_Seconds) * 1000); const s = summarize(ms);
      card.innerHTML = `<h3>${persistent ? "Keep-alive" : "Close after response"}</h3><p class="meta">${r.count} requests · mean ${s.mean.toFixed(2)} ms · median ${s.med.toFixed(2)} ms · sd ${s.sd.toFixed(2)} · ${esc(r.finished)}</p>
        <div class="table-wrap"><table class="data"><thead><tr><th>#</th><th class="num">Time</th><th>Cache</th></tr></thead><tbody>${r.rows.map((x) => `<tr><td class="mono">${esc(x.Request)}</td><td class="num">${(Number(x.Response_Time_Seconds) * 1000).toFixed(2)} ms</td><td>${cacheBadge(x.Cache_Status)}</td></tr>`).join("")}</tbody></table></div>`;
    } catch (err) { $("#quick-out").insertAdjacentHTML("afterbegin", `<p class="field-error">${esc(err.message)}</p>`); }
    finally { btn.disabled = false; btn.classList.remove("busy"); }
  };
  $("#q-close").addEventListener("click", (e) => quick(false, e.currentTarget));
  $("#q-keep").addEventListener("click", (e) => quick(true, e.currentTarget));
  pollFormal();
}

/* ---------------------------------------------------------------- evidence */
const CHECKS = [
  "Capture on H2 (the proxy): it sees both links, client↔proxy and proxy↔origin",
  "Pick the Wi-Fi or Ethernet adapter, not the loopback adapter",
  "Note the IP of every host (ipconfig) before starting",
  "Start the capture before sending the first request",
  "Send PURGE, then GET twice: one MISS, one HIT",
  "Stop the capture and save it as .pcapng",
  "Annotate one client GET on port 9090: Ethernet, IPv4, TCP, Data",
  "Screenshot Follow → TCP Stream showing the CNTP text",
];
const FILTERS = [
  ["tcp.port == 9090 || tcp.port == 8080", "Both CNTP links"],
  ["tcp.port == 9090", "Client ↔ proxy only"],
  ["tcp.port == 8080", "Proxy ↔ origin only (appears on a MISS)"],
  ["tcp.port == 9090 && tcp.len > 0", "Packets that carry CNTP data"],
  ["tcp.flags.syn == 1", "Connection openings (count handshakes)"],
  ['frame contains "CNTP/1.0"', "Any packet with a CNTP start line"],
];
const SCENARIO = [
  "Capture while sending a GET that is a MISS (PURGE it first).",
  "Send the same GET again: a HIT. Compare whether traffic to :8080 appears for each.",
  "Run the page fetch with keep-alive, then with close after response, and count SYN packets.",
  "Follow one TCP stream and point out the start line, CRLF separator, Content-Length and X-Cache.",
  "Stop the origin, GET an uncached object, and capture the 502 with the refused SYN to :8080.",
];
const GLOSSARY = [
  ["TCP handshake", "SYN, SYN-ACK, ACK. Opening a connection costs about one round trip before any CNTP byte is sent."],
  ["TCP stream", "The ordered byte stream of one connection. CNTP messages are framed inside it by CRLF CRLF and Content-Length."],
  ["Payload", "The bytes inside the TCP segment: here, the CNTP request or response text."],
  ["Client ↔ proxy hop", "H3 to H2 on port 9090. Every request uses it."],
  ["Proxy ↔ origin hop", "H2 to H1 on port 8080. Only a cache MISS uses it."],
  ["Persistent connection", "Keep-alive: several requests on one TCP connection, so only the first pays the handshake."],
  ["Cache HIT / MISS", "HIT: a fresh copy answered from H2's memory. MISS: missing or expired, so fetched from H1 and stored for Max-Age seconds."],
  ["Max-Age", "Seconds the origin allows the proxy to reuse a response. Long saves traffic; short keeps data fresh."],
];
function setupEvidence() {
  const done = store.get("checks", []);
  $("#checklist").innerHTML = CHECKS.map((c, i) => `<li><label><input type="checkbox" data-i="${i}" ${done.includes(i) ? "checked" : ""}><span>${esc(c)}</span></label></li>`).join("");
  $("#checklist").addEventListener("change", () => store.set("checks", $$("#checklist input:checked").map((i) => Number(i.dataset.i))));
  $("#filters").innerHTML = FILTERS.map(([f, w]) => `<li><div><code>${esc(f)}</code><span class="what">${esc(w)}</span></div>${copyBtn(f)}</li>`).join("");
  $("#scenario").innerHTML = SCENARIO.map((s) => `<li>${esc(s)}</li>`).join("");
  $("#glossary").innerHTML = GLOSSARY.map(([t, d]) => `<div><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join("");
  const notes = $("#notes"); notes.value = store.get("notes", "");
  let t; notes.addEventListener("input", () => { clearTimeout(t); $("#notes-saved").textContent = "Saving…"; t = setTimeout(() => { store.set("notes", notes.value); $("#notes-saved").textContent = "Saved in this browser"; }, 400); });
}
function copyBtn(text) { return `<button class="icon-btn copy-btn" data-copy="${esc(text)}" aria-label="Copy ${esc(text)}" title="Copy"><svg class="ico"><use href="#i-copy"/></svg></button>`; }
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]"); if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); } catch { const ta = document.createElement("textarea"); ta.value = b.dataset.copy; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
  b.classList.add("done"); b.querySelector("use").setAttribute("href", "#i-check");
  setTimeout(() => { b.classList.remove("done"); b.querySelector("use").setAttribute("href", "#i-copy"); }, 1200);
});

/* ---------------------------------------------------------------- failure lab */
const CLIENT_FAULTS = [
  { kind: "idle", title: "Idle client", expect: "408 Request Timeout after ~15 s, then the proxy closes the connection", how: "Opens a TCP connection to the proxy and sends nothing.", slow: true },
  { kind: "reset", title: "Client disconnects mid-transfer", expect: "Proxy logs \"Connection lost\" and keeps serving: the next GET returns 200", how: "PURGEs /large.txt so the proxy fetches it, reads 1 KB, then resets the connection (RST)." },
  { kind: "malformed", title: "Malformed request", expect: "400 Bad Request", how: "Sends GARBAGE followed by a blank line." },
  { kind: "version", title: "Wrong protocol version", expect: "505 Version Not Supported", how: "Sends GET /index.html HTTP/1.1, exactly what a browser would send." },
  { kind: "method", title: "Unsupported method", expect: "405 Method Not Allowed with Allow: GET, HEAD, PURGE, STATS", how: "Sends DELETE /index.html CNTP/1.0." },
];
const HOST_SCENARIOS = [
  { title: "Origin down → 502", steps: ["On H1 press Ctrl+C on server.py.", "Here: Force a MISS. Expect 502 Bad Gateway; the proxy stays up.", "Here: Cached GET. A still-fresh object returns 200 HIT: the cache keeps serving.", "Restart server.py on H1 and Force a MISS again: 200."] },
  { title: "Slow origin → 504", steps: ["On H1 restart with: python server.py --delay 6", "Here: Force a MISS. Expect 504 Gateway Timeout after 5 s.", "Restart H1 without --delay afterwards."] },
  { title: "Proxy down", steps: ["On H2 press Ctrl+C on proxy.py.", "Here: Force a MISS or Cached GET. Expect connection refused, and the top bar shows the proxy Unreachable.", "Restart proxy.py on H2; the next request works."] },
];
const PROBES = [
  { kind: "miss", title: "Force a MISS", expect: "200 MISS normally · 502 with H1 stopped · 504 with H1 --delay 6", how: "PURGE the path, then GET it, so the proxy must contact the origin.", path: true },
  { kind: "cached", title: "Cached GET", expect: "200 HIT while /index.html is fresh, even with H1 stopped", how: "GET /index.html. Fetch it once before stopping H1 so it is cached." },
];
const faultLog = [];

function faultCard(f) {
  return `<div class="fault" data-kind="${f.kind}">
    <div class="fault-main"><h3>${esc(f.title)}</h3><p class="muted small">${esc(f.how)}</p><p class="small"><span class="muted">Expected:</span> ${esc(f.expect)}</p></div>
    <div class="fault-act">${f.path ? `<label class="sr" for="fp-${f.kind}">Path</label><select class="field mono" id="fp-${f.kind}"><option>/about.html</option><option>/notes.txt</option><option>/logo.png</option><option>/large.txt</option><option>/index.html</option></select>` : ""}
      <button class="btn" type="button" data-run="${f.kind}"><svg class="ico"><use href="#i-play"/></svg>Run</button></div>
    <div class="fault-result" id="fr-${f.kind}" hidden></div></div>`;
}

function setupFaults() {
  $("#fault-client").innerHTML = CLIENT_FAULTS.map(faultCard).join("");
  $("#fault-hosts").innerHTML = HOST_SCENARIOS.map((s) => `<div class="scenario"><h3>${esc(s.title)}</h3><ol class="steps">${s.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol></div>`).join("");
  $("#fault-probes").innerHTML = PROBES.map(faultCard).join("");
  $('[data-page="faults"]').addEventListener("click", async (e) => {
    const b = e.target.closest("[data-run]"); if (!b) return;
    const kind = b.dataset.run, def = [...CLIENT_FAULTS, ...PROBES].find((f) => f.kind === kind);
    const out = $(`#fr-${kind}`);
    b.disabled = true; b.classList.add("busy"); out.hidden = false;
    let tick;
    if (def.slow) { let s = 0; out.innerHTML = `<p class="muted small mono">waiting for the proxy… 0 s</p>`; tick = setInterval(() => { s++; out.innerHTML = `<p class="muted small mono">waiting for the proxy… ${s} s</p>`; }, 1000); }
    else out.innerHTML = '<p class="muted small mono">running…</p>';
    let r;
    try { r = await api("/api/fault", { kind, path: def.path ? $(`#fp-${kind}`).value : undefined }); }
    catch (err) { r = { kind, time: new Date().toLocaleTimeString([], { hour12: false }), error: err.message, unreachable: !!err.data?.unreachable, expected: def.expect, passed: null }; }
    finally { clearInterval(tick); b.disabled = false; b.classList.remove("busy"); }
    r.title = def.title;
    faultLog.unshift(r);
    out.innerHTML = faultResult(r);
    renderFaultLog();
    if (r.unreachable) checkHealth();
  });
  $("#fault-copy").addEventListener("click", async (e) => {
    const text = faultLog.slice().reverse().map(faultText).join("\n\n") || "No tests run yet.";
    try { await navigator.clipboard.writeText(text); e.currentTarget.classList.add("done"); setTimeout(() => $("#fault-copy").classList.remove("done"), 1200); } catch { /* clipboard blocked */ }
  });
}
function verdict(r) {
  if (r.error) return `<span class="badge err">${r.unreachable ? "PROXY UNREACHABLE" : "FAILED"}</span>`;
  if (r.passed === true) return '<span class="badge hit">AS DESIGNED</span>';
  if (r.passed === false) return '<span class="badge err">UNEXPECTED</span>';
  const code = Number((r.status_line || "").split(" ")[1]);
  return code >= 500 ? `<span class="badge err">${code}</span>` : r.cache ? cacheBadge(r.cache) : '<span class="badge none">RECORDED</span>';
}
function faultResult(r) {
  if (r.error) return `<div class="fr-head">${verdict(r)}<span class="mono small">${esc(r.error)}</span></div>`;
  return `<div class="fr-head">${verdict(r)}<span class="mono small">${esc(r.status_line || "no response")}</span><span class="muted small mono">${r.elapsed_s} s · ${r.received_bytes} B received${r.closed_by_proxy ? " · closed by proxy" : ""}</span></div>
    ${r.followup ? `<p class="small mono">${esc(r.followup)}</p>` : ""}
    <details><summary class="small">Bytes sent and received</summary><pre class="viewer">${esc(r.sent || "(nothing sent)")}\n──────── response ────────\n${esc(r.received || "(nothing received)")}</pre></details>`;
}
function faultText(r) {
  const head = `[${r.time}] ${r.title} -> ${r.target || state.config?.proxy.host + ":" + state.config?.proxy.port}`;
  if (r.error) return `${head}\n  result: ${r.error}`;
  return `${head}\n  expected: ${r.expected}\n  got: ${r.status_line || "no response"} | ${r.elapsed_s} s | ${r.received_bytes} bytes${r.closed_by_proxy ? " | closed by proxy" : ""}${r.cache ? " | X-Cache " + r.cache : ""}${r.followup ? "\n  " + r.followup : ""}\n  verdict: ${r.passed === true ? "as designed" : r.passed === false ? "UNEXPECTED" : "recorded"}`;
}
function renderFaultLog() {
  $("#fault-empty").hidden = faultLog.length > 0;
  $("#fault-log").innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Time</th><th>Test</th><th>Result</th><th>Response</th><th class="num">Elapsed</th></tr></thead><tbody>${faultLog.map((r) => `<tr><td class="mono">${esc(r.time)}</td><td>${esc(r.title)}</td><td>${verdict(r)}</td><td class="mono">${esc(r.error || r.status_line || "—")}</td><td class="num">${r.error ? "—" : r.elapsed_s + " s"}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ---------------------------------------------------------------- host check */
async function runHostCheck() {
  $("#hc-strip").innerHTML = '<span class="muted small">Checking hosts…</span>';
  try { state.hc = await api("/api/hostcheck"); }
  catch (e) { state.hc = null; $("#hc-strip").innerHTML = `<span class="status-err small">${esc(e.message)}</span>`; return; }
  renderHostCheck();
  if (!$('[data-page="overview"]').hidden) drawTopology();
}
function renderHostCheck() {
  const hc = state.hc; if (!hc) return;
  const icon = (ok) => ok === true ? '<svg class="ico ok"><use href="#i-check"/></svg>' : ok === false ? '<svg class="ico bad"><use href="#i-x"/></svg>' : '<svg class="ico warn"><use href="#i-fault"/></svg>';
  const h = hc.hosts;
  const title = hc.verdict === "three-hosts" ? "Three separate hosts confirmed" : hc.verdict === "local" ? "Local lab: every role on this machine" : "Host check incomplete";
  const cls = hc.verdict === "three-hosts" ? "ok" : hc.verdict === "local" ? "warn" : "bad";
  $("#hc-strip").innerHTML = `<span class="hc-verdict ${cls}">${icon(hc.verdict === "three-hosts" ? true : hc.verdict === "local" ? null : false)}${title}</span>
    <span class="hc-hosts mono"><b>H3</b> ${esc(h.h3 || "?")}<b>H2</b> ${esc(h.h2 || "?")}<b>H1</b> ${esc(h.h1 || "?")}</span>
    <a href="#config" class="small">Details</a>`;
  $("#hc-time").textContent = `checked ${hc.checked}`;
  $("#hc-detail").innerHTML = `<ul class="checks">${hc.checks.map((c) => `<li>${icon(c.ok)}<div><b>${esc(c.text)}</b><span class="mono small">${esc(c.detail)}</span></div></li>`).join("")}</ul>`;
}

/* ---------------------------------------------------------------- config */
function renderBanner() {
  const c = state.config, saved = store.get("setup", null), b = $("#banner");
  const isLocal = c.setup === "LOCAL LAB", partly = c.setup === "PARTLY LOCAL";
  const offer = saved && (saved.proxy_host !== c.proxy.host || saved.origin_host !== c.origin.host) && !saved.proxy_host.startsWith("127.");
  if (!isLocal && !partly) { b.hidden = true; return; }
  b.hidden = false;
  b.className = "banner " + (partly ? "bad" : "warn");
  b.innerHTML = `<svg class="ico"><use href="#i-fault"/></svg><span>${isLocal ? "<b>Local lab.</b> Client, proxy and origin all run on this machine: fine for development, not valid for R3." : "<b>Partly local.</b> One role is on 127.0.0.1, so this is not a three-host run."}</span>
    ${offer ? `<button class="btn" type="button" id="banner-saved">Connect to H2 ${esc(saved.proxy_host)} · H1 ${esc(saved.origin_host)}</button>` : ""}
    <a class="btn" href="#config">Set up hosts</a>`;
  $("#banner-saved")?.addEventListener("click", () => applySetup(saved));
}
async function applySetup(values, btn) {
  $("#s-err").textContent = "";
  btn?.classList.add("busy"); if (btn) btn.disabled = true;
  try {
    state.config = await api("/api/config", values);
    if (!values.proxy_host.startsWith("127.")) store.set("setup", values);
    renderConfig(); await checkHealth(); await runHostCheck(); refreshStats();
  } catch (e) { $("#s-err").textContent = e.message; }
  finally { btn?.classList.remove("busy"); if (btn) btn.disabled = false; }
}
function setupConfigForm() {
  $("#setup-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = { proxy_host: $("#s-proxy-host").value.trim(), proxy_port: Number($("#s-proxy-port").value), origin_host: $("#s-origin-host").value.trim(), origin_port: Number($("#s-origin-port").value) };
    if (!v.proxy_host || !v.origin_host) { $("#s-err").textContent = "Enter both IP addresses (run ipconfig on H2 and H1)."; return; }
    applySetup(v, $("#s-apply"));
  });
  $("#s-local").addEventListener("click", (e) => applySetup({ proxy_host: "127.0.0.1", proxy_port: 9090, origin_host: "127.0.0.1", origin_port: 8080 }, e.currentTarget));
}
function renderConfig() {
  const c = state.config;
  $("#rail-target").textContent = `${c.proxy.host}:${c.proxy.port}`;
  const chip = $("#setup-chip"); chip.textContent = c.setup; chip.hidden = false;
  $("#lab-target").textContent = `Target: ${c.proxy.host}:${c.proxy.port} · ${c.version}`;
  $("#s-proxy-host").value = c.proxy.host; $("#s-proxy-port").value = c.proxy.port;
  $("#s-origin-host").value = c.origin.host; $("#s-origin-port").value = c.origin.port;
  $("#cfg-source").textContent = `current values: ${c.source}`;
  renderBanner();
  $("#cfg-table").innerHTML = `<tbody>
    <tr><td>Protocol</td><td class="mono">${esc(c.version)} over TCP</td></tr>
    <tr><td>This UI (browser ↔ ui.py)</td><td class="mono">http://${esc(c.ui)} · local HTTP, not CNTP</td></tr>
    <tr><td>Proxy (H2), requests go here</td><td class="mono">${esc(c.proxy.host)}:${c.proxy.port}</td></tr>
    <tr><td>Origin (H1), host check and top bar</td><td class="mono">${esc(c.origin.host)}:${c.origin.port}</td></tr>
    <tr><td>Setup</td><td class="mono">${esc(c.setup)}</td></tr>
    <tr><td>Python on this host</td><td class="mono">${esc(c.python)}</td></tr></tbody>`;
  const local = c.setup === "LOCAL LAB";
  const H1 = local ? "<H1-IP>" : c.origin.host, H2 = local ? "<H2-IP>" : c.proxy.host;
  const cmd = (who, note, line) => `<div class="cmd"><div class="cmd-head"><b>${who}</b><span class="muted small">${note}</span></div><div class="cmd-row"><code>${esc(line)}</code>${copyBtn(line)}</div></div>`;
  $("#runbook").innerHTML = `<h3 style="margin-top:0">Three hosts</h3>
    ${cmd("H1 · origin", "serves www/ on port 8080", "python server.py --port 8080 --max-age 60")}
    ${cmd("H2 · proxy", "caches on port 9090, forwards misses to H1", `python -u proxy.py --origin-host ${H1} --port 9090`)}
    ${cmd("H3 · this UI", "open http://127.0.0.1:3000", `python ui.py --proxy-host ${H2} --origin-host ${H1}`)}
    ${cmd("H3 · benchmark", "R6 measurements, at least 5 runs", `python bench.py --proxy-host ${H2} --label wifi --runs 10`)}
    ${cmd("H3 · graphs", "PNG charts + summary table into results/plots/", "python plot_results.py")}
    <h3>One machine (development only, not valid for R3)</h3>
    ${cmd("All", "three terminals in the project folder", "python server.py  |  python proxy.py  |  python ui.py")}`;
}

/* ---------------------------------------------------------------- boot */
async function boot() {
  $("#menu-btn").addEventListener("click", () => { const o = $("#rail").classList.toggle("open"); $("#menu-btn").setAttribute("aria-expanded", String(o)); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeRail(); hideTip(); } });
  $("#refresh-btn").addEventListener("click", () => { checkHealth(true); refreshStats(); runHostCheck(); });
  $("#activity tbody").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) { state.selected = Number(tr.dataset.id); location.hash = "#inspector"; } });
  $("#activity tbody").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.closest("tr[data-id]")?.click(); });
  $("#insp-select").addEventListener("change", (e) => { state.selected = Number(e.target.value); renderInspector(); });
  $$('input[name="iv"]').forEach((i) => i.addEventListener("change", renderInspector));
  window.addEventListener("hashchange", route);
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (!$('[data-page="overview"]').hidden) drawTopology(); }, 150); });
  setupRequestLab(); setupBench(); setupFaults(); setupEvidence(); setupConfigForm(); renderActivity();
  try { state.config = await api("/api/config"); renderConfig(); }
  catch (e) { $("#last-op").innerHTML = `<span class="status-err">${esc(e.message)}</span>`; }
  route();
  await checkHealth();
  runHostCheck();
  // Reachability every 15 s (silent on the hosts: a connect-and-close is not logged).
  // Proxy STATS refreshes only on page open, after each request and on the refresh button,
  // so H2's console shows real traffic rather than polling.
  setInterval(checkHealth, 15000);
}
boot();
