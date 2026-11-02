/* VSR Scaffold Planner — MVP frontend (no build step). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 2) => (v === null || v === undefined || v === "") ? "–" : (typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: 0 }) : esc(v));
const PHASE = { base_jack: 0, standard: 1, ledger: 2, transom: 3, diagonal: 4, bracket: 5, advance_guardrail: 6, deck: 7, guardrail: 8, toe_board: 9, tie: 10, wedge: 11, infill: 12 };
const SYS_COLOR = { SM8: "#c2410c", LAYHER_LW: "#1d4ed8" };
const sysColor = (s) => SYS_COLOR[s] || "#6d28d9";

const state = { meta: null, project: null, areaId: null, run: null, anim: null };

async function api(path, opts = {}) {
  const headers = Object.assign({ "X-VSR-Role": $("#roleSel").value }, opts.headers || {});
  if (opts.body && !(opts.body instanceof FormData)) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.body); }
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).detail; } catch (e) { /* plain */ } throw new Error(`${r.status}: ${typeof t === "string" ? t : JSON.stringify(t)}`); }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}
function toast(msg, bad) { const d = document.createElement("div"); d.className = "warnbox"; d.style.cssText = "position:fixed;right:16px;bottom:50px;z-index:9;max-width:520px;" + (bad ? "border-color:#fca5a5;background:#fef2f2" : ""); d.textContent = msg; document.body.appendChild(d); setTimeout(() => d.remove(), bad ? 9000 : 3500); }
async function busy(btn, fn) { btn.disabled = true; try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; } }

/* ---------------------------------------------------------------- init */
async function init() {
  state.meta = await api("/api/meta");
  $("#disclaimer").textContent = "⚠ " + state.meta.disclaimer;
  $$("#tabs button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
  $("#projectSel").onchange = () => loadProject($("#projectSel").value);
  await loadProjects();
  $("#newArea").onclick = () => editArea(null);
  $("#saveArea").onclick = (e) => busy(e.target, saveArea);
  $("#runArea").onclick = (e) => busy(e.target, runArea);
  $("#delArea").onclick = (e) => busy(e.target, deleteArea);
  $("#runAll").onclick = (e) => busy(e.target, async () => { await api(`/api/projects/${state.project.id}/run-all`, { method: "POST", body: { crew: +$("#crew").value } }); await loadProject(state.project.id, state.areaId); toast("All areas run."); });
  $("#uploadBtn").onclick = (e) => busy(e.target, uploadDrawing);
  $("#msPreview").onclick = () => { $("#msSvg").innerHTML = miniSection(manualSection()); };
  $("#msSave").onclick = (e) => busy(e.target, async () => { await api(`/api/projects/${state.project.id}/sections`, { method: "POST", body: manualSection() }); await loadProject(state.project.id); toast("Section saved (confidence low until verified)."); });
}
function showTab(t) { $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t)); $$(".tab").forEach((s) => s.classList.toggle("on", s.id === "tab-" + t)); if (t === "summary") renderSummary(); if (t === "catalogues") renderCatalogues(); if (t === "drawings") renderDrawings(); }

async function loadProjects() {
  const ps = await api("/api/projects");
  if (!ps.length) { await api("/api/projects/sample", { method: "POST" }); return loadProjects(); }
  $("#projectSel").innerHTML = ps.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  await loadProject(ps[0].id);
}
async function loadProject(pid, keepArea) {
  state.project = await api(`/api/projects/${pid}`);
  renderAreaList();
  const a = keepArea || state.areaId || state.project.areas[0]?.id;
  if (a && state.project.areas.find((x) => x.id === a)) await selectArea(a); else editArea(null);
  if ($("#tab-drawings").classList.contains("on")) renderDrawings();
}

/* ---------------------------------------------------------------- areas */
const AREA_FIELDS = [
  ["id", "Area id", "text"], ["name", "Name", "text"],
  ["area_type", "Area type", ["flat_shell", "curved_shell", "bow_flare", "stern_bilge_turn", "internal_compartment", "deck_edge", "superstructure", "tower"]],
  ["section_id", "Section (frame)", "section"], ["face", "Scaffold side of surface", ["outboard", "inboard"]], ["side", "Ship side", ["SB", "PS"]],
  ["frame_from", "Frame from", "num"], ["frame_to", "Frame to", "num"], ["frame_spacing_m", "Frame spacing (m)", "num"], ["run_length_m", "Run length override (m)", "num"],
  ["run_start", "Run start", ["free", "bounded"]], ["run_end", "Run end", ["free", "bounded"]], ["run_tolerance_m", "Run end tolerance (m)", "num"], ["max_overhang_m", "Max overhang at free end (m)", "num"],
  ["z_base", "Standing level z (m)", "num"], ["z_top", "Top of work z (m)", "num"], ["n_lifts", "Lifts (blank = auto)", "num"], ["working_levels", "Working levels (lifts, comma; blank = all)", "list"],
  ["clearance_target_m", "Clearance target (m)", "num"], ["gap_min_m", "Min gap / clash clearance (m)", "num"], ["max_gap_m", "Max gap (blank = catalogue)", "num"],
  ["load_class", "Load class", ["3", "4", "5", "6"]], ["anchorage", "Anchorage", ["tied", "free_standing", "suspended"]], ["protection", "Side protection", ["outer", "all_sides"]],
  ["advance_guardrail", "Advance guardrail", "bool"], ["min_platform_width_m", "Min platform width (m)", "num"], ["max_extra_rows", "Max stepped inner lines", "num"],
  ["obstruction_mode", "Obstructions", ["avoid", "flag_only"]], ["use_drawing_obstructions", "Use obstructions from drawing", "bool"], ["rental_months", "Rental months", "num"],
  ["tower_bays", "Tower: bays", "num"], ["tower_bay_target_m", "Tower: bay length target", "num"], ["tower_width_target_m", "Tower: width target", "num"], ["notes", "Notes", "text"],
];
function renderAreaList() {
  const runs = state.project.runs || [];
  $("#areaList").innerHTML = state.project.areas.map((a) => {
    const r = runs.find((x) => x.area_id === a.id);
    return `<li data-id="${esc(a.id)}" class="${a.id === state.areaId ? "on" : ""}">${esc(a.name)}<small>${esc(a.id)} · ${esc(a.area_type)}${r ? " · run " + esc(r.run_id) : " · not run"}</small></li>`;
  }).join("");
  $$("#areaList li").forEach((li) => li.onclick = () => selectArea(li.dataset.id));
}
async function selectArea(aid) {
  state.areaId = aid; renderAreaList();
  editArea(state.project.areas.find((a) => a.id === aid));
  const r = (state.project.runs || []).find((x) => x.area_id === aid);
  $("#result").innerHTML = r ? "<p class='muted'>Loading last run…</p>" : "<p class='muted'>Not run yet — press <b>Run simulation</b>.</p>";
  if (r) renderResult(await api(`/api/runs/${r.run_id}`));
}
function editArea(a) {
  const d = a || { id: "A-" + Math.random().toString(36).slice(2, 6).toUpperCase(), name: "New area", area_type: "flat_shell", frame_spacing_m: state.project?.frame_spacing_m || 0.7, z_base: -1.4, z_top: 14, clearance_target_m: 0.2, gap_min_m: 0.05, load_class: 4, anchorage: "tied", protection: "outer", advance_guardrail: true, min_platform_width_m: 0.9, max_extra_rows: 3, run_tolerance_m: 0.2, max_overhang_m: 1.0, rental_months: 1, face: "outboard", side: "SB", run_start: "free", run_end: "free", obstruction_mode: "avoid", section_id: state.project?.sections[0]?.id };
  if (!a) { state.areaId = null; $("#result").innerHTML = ""; renderAreaList(); }
  $("#areaTitle").textContent = a ? `— ${a.name}` : "— new";
  const secs = state.project?.sections || [];
  $("#areaForm").innerHTML = AREA_FIELDS.map(([k, label, t]) => {
    const v = d[k];
    let inp;
    if (Array.isArray(t)) inp = `<select name="${k}">${t.map((o) => `<option ${String(v) === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    else if (t === "section") inp = `<select name="${k}"><option value="">(none — tower / manual)</option>${secs.map((s) => `<option value="${esc(s.id)}" ${v === s.id ? "selected" : ""}>${esc(s.id)} · ${esc(s.source)} · ${esc(s.confidence)}</option>`).join("")}</select>`;
    else if (t === "bool") inp = `<input type="checkbox" name="${k}" ${v ? "checked" : ""}>`;
    else if (t === "list") inp = `<input name="${k}" value="${esc((v || []).join(","))}">`;
    else inp = `<input name="${k}" ${t === "num" ? 'type="number" step="any"' : ""} value="${esc(v ?? "")}">`;
    return `<label>${esc(label)}${inp}</label>`;
  }).join("");
}
function readArea() {
  const o = {};
  for (const [k, , t] of AREA_FIELDS) {
    const el = $(`#areaForm [name="${k}"]`);
    if (t === "bool") o[k] = el.checked;
    else if (t === "num") o[k] = el.value === "" ? null : +el.value;
    else if (t === "list") o[k] = el.value.trim() ? el.value.split(",").map((x) => +x.trim()).filter((x) => !isNaN(x)) : null;
    else if (k === "load_class") o[k] = +el.value;
    else o[k] = el.value === "" ? null : el.value;
  }
  const old = state.project.areas.find((a) => a.id === o.id);
  if (old?.obstructions) o.obstructions = old.obstructions;
  for (const k of Object.keys(o)) if (o[k] === null && !["section_id", "run_length_m", "n_lifts", "max_gap_m", "working_levels", "frame_from", "frame_to", "tower_bays", "tower_bay_target_m", "tower_width_target_m"].includes(k)) delete o[k];
  return o;
}
async function saveArea() { const a = readArea(); await api(`/api/projects/${state.project.id}/areas`, { method: "POST", body: a }); state.areaId = a.id; await loadProject(state.project.id, a.id); toast("Area saved."); }
async function runArea() {
  const a = readArea(); await api(`/api/projects/${state.project.id}/areas`, { method: "POST", body: a });
  state.areaId = a.id;
  const run = await api(`/api/projects/${state.project.id}/areas/${a.id}/run`, { method: "POST", body: { crew: +$("#crew").value } });
  state.project = await api(`/api/projects/${state.project.id}`); renderAreaList(); renderResult(run);
}
async function deleteArea() { if (!state.areaId || !confirm("Delete area " + state.areaId + "?")) return; await api(`/api/projects/${state.project.id}/areas/${state.areaId}`, { method: "DELETE" }); state.areaId = null; await loadProject(state.project.id); }

/* ---------------------------------------------------------------- results */
function confBadge(c) { return `<span class="badge conf-${esc(c)}">geometry ${esc(c)}</span>`; }
function renderResult(run) {
  state.run = run;
  if (state.anim) { cancelAnimationFrame(state.anim.raf); state.anim = null; }
  const c = run.comparison, systems = Object.keys(run.results), snap = run.snapshot;
  const errors = systems.flatMap((s) => run.results[s].layout.violations.filter((v) => v.severity === "error").map((v) => [s, v]));
  const estShare = systems.map((s) => [s, run.results[s].metrics.estimate_weight_share.value]);
  let h = `<div class="panel headline"><div>
    <div class="muted">Recommendation for ${esc(snap.area.name)} ${confBadge(run.geometry_confidence)}</div>
    <div class="reco"><span class="sys-${esc(c.recommended)}" style="color:${sysColor(c.recommended)}">${esc(run.results[c.recommended].system_name)}</span>
      ${c.margin_pct !== null ? `<span class="muted" style="font-size:15px">margin ${fmt(c.margin_pct, 1)}% over ${esc(c.runner_up)}</span>` : ""}</div>
    <ol>${(c.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ol>
    <div><b>Sensitivity</b><ul class="flags">${(c.sensitivity || []).map((s) => `<li>${esc(s.text)}</li>`).join("")}</ul></div>
  </div><div>
    <div class="small-print">Run <code>${esc(run.run_id)}</code> · ${esc(run.created)} · crew ${snap.crew} · geometry ${esc(snap.geometry.source)} ${esc(snap.geometry.source_file || "")} ${snap.geometry.frame !== null ? "· FR " + esc(snap.geometry.frame) : ""}</div>
    <ul class="small-print">${systems.map((s) => { const v = snap.versions[s]; return `<li><b>${esc(s)}</b>: catalogue ${esc(v.catalogue.catalogue_version)} <code>${esc(v.catalogue.sha256)}</code> (${v.catalogue.estimates} estimate items) · time standard ${esc(v.time_standard.version)} <b>[${esc(v.time_standard.status)}]</b></li>`; }).join("")}</ul>
    ${estShare.filter(([, v]) => v > 0).map(([s, v]) => `<div class="warnbox">⚠ ${esc(s)}: ${fmt(v * 100, 0)}% of weight from <b>estimate</b> figures (not verified).</div>`).join("")}
    ${errors.length ? `<div class="warnbox" style="border-color:#fca5a5"><b>Rule violations (error):</b><ul>${errors.map(([s, v]) => `<li><b>${esc(s)}</b>: ${esc(v.message)}</li>`).join("")}</ul></div>` : ""}
    <div class="row">
      <a href="/api/runs/${esc(run.run_id)}/excel"><button>Excel</button></a>
      ${systems.map((s) => `<a href="/api/runs/${esc(run.run_id)}/trace/${esc(s)}.csv"><button class="small">Trace ${esc(s)} CSV</button></a>`).join("")}
      <a href="report.html?run=${esc(run.run_id)}" target="_blank"><button class="primary">Management report</button></a>
    </div>
  </div></div>`;
  // views + player
  const maxMin = Math.max(...systems.map((s) => run.results[s].simulation.elapsed_min));
  h += `<div class="panel"><div class="player"><button id="play">▶ Play</button><input id="scrub" type="range" min="0" max="${maxMin}" step="${maxMin / 600}" value="${maxMin}">
      <span id="tlabel" class="muted"></span><label class="muted">speed <select id="speed"><option value="10">×10</option><option value="30" selected>×30</option><option value="120">×120</option></select></label></div>
      <div class="views">${systems.map((s) => `<div class="view"><h4 style="color:${sysColor(s)}">${esc(run.results[s].system_name)} ${run.results[s].valid ? "" : '<span class="badge sev-error">invalid</span>'}</h4>
      <div class="counters" id="cnt-${esc(s)}"></div>${sectionSvg(run, s)}${elevationSvg(run, s)}</div>`).join("")}</div>
      <div class="small-print">Red = tube-and-coupler infill. Orange = brackets. Section view: Y outboard → right, Z up${run.results[systems[0]].layout.mirrored ? " (inboard face shown mirrored)" : ""}. Elevation: X along the run with frame numbers.</div></div>`;
  // comparison table
  h += `<div class="panel"><h3>Comparison — full calculation</h3><table><tr><th>Criterion</th><th>Unit</th><th class="num">Weight</th>${systems.map((s) => `<th class="num">${esc(s)} raw</th><th class="num">norm.</th><th class="num">weighted</th>`).join("")}</tr>
    ${c.table.map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.unit)}</td><td class="num">${fmt(r.weight)}</td>${systems.map((s) => `<td class="num">${fmt(r.systems[s].raw, 3)}</td><td class="num">${fmt(r.systems[s].normalised, 3)}</td><td class="num">${fmt(r.systems[s].weighted, 3)}</td>`).join("")}</tr>`).join("")}
    <tr><th colspan="3">Total score</th>${systems.map((s) => `<th></th><th></th><th class="num" style="color:${sysColor(s)}">${fmt(c.totals[s], 4)}</th>`).join("")}</tr></table>
    <p class="small-print">${esc(c.method)}</p>
    <details><summary>Re-score with other weights</summary><div class="row">${Object.entries(c.weights).map(([k, v]) => `<label>${esc(k)}<input type="number" step="0.05" data-w="${esc(k)}" value="${v}"></label>`).join("")}<button id="rescore">Re-score</button></div><div id="rescoreOut"></div></details></div>`;
  // metrics
  const names = Object.keys(run.results[systems[0]].metrics);
  h += `<div class="panel"><h3>Metrics (hover a formula for its inputs)</h3><table><tr><th>Metric</th><th>Unit</th>${systems.map((s) => `<th class="num">${esc(s)}</th>`).join("")}<th>Formula / trace</th></tr>
    ${names.map((n) => { const m0 = run.results[systems[0]].metrics[n]; return `<tr><td>${esc(n)}</td><td>${esc(m0.unit)}</td>${systems.map((s) => `<td class="num">${fmt(run.results[s].metrics[n].value, 3)}</td>`).join("")}<td title="${esc(JSON.stringify(m0.inputs))}">${esc(m0.formula)}</td></tr>`; }).join("")}</table></div>`;
  // layout detail, rules, BoM
  h += `<div class="panel"><div class="tabs2">${systems.map((s, i) => `<button data-sys="${esc(s)}" class="${i ? "" : "on"}">${esc(s)}</button>`).join("")}</div><div id="sysDetail"></div></div>`;
  $("#result").innerHTML = h;
  $$(".tabs2 button").forEach((b) => b.onclick = () => { $$(".tabs2 button").forEach((x) => x.classList.toggle("on", x === b)); renderSysDetail(run, b.dataset.sys); });
  renderSysDetail(run, systems[0]);
  $("#rescore").onclick = async () => { const w = {}; $$("[data-w]").forEach((i) => w[i.dataset.w] = +i.value); const r = await api(`/api/runs/${run.run_id}/rescore`, { method: "POST", body: { weights: w } }); $("#rescoreOut").innerHTML = `<p><b>${esc(r.recommended)}</b> (margin ${fmt(r.margin_pct, 1)}%) — ${Object.entries(r.totals).map(([s, v]) => `${esc(s)} ${fmt(v, 4)}`).join(" · ")}</p><ul>${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`; };
  setupPlayer(run, maxMin);
}
function renderSysDetail(run, s) {
  const res = run.results[s], L = res.layout;
  const tot = res.bom.reduce((a, b) => a + b.total_weight_kg, 0);
  $("#sysDetail").innerHTML = `<h3>Layout</h3><ul>${L.explanation.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>
  <table><tr><th>Lift</th><th class="num">Deck z</th><th>Status</th><th class="num">Gap (m)</th><th class="num">Bracket</th><th class="num">Lines</th><th>Reason</th></tr>
  ${L.lifts.map((lp) => `<tr><td>${lp.k}</td><td class="num">${fmt(lp.z_deck)}</td><td class="${lp.status === "infill" ? "sev-error" : lp.status === "bracket" ? "sev-warning" : ""}">${esc(lp.status)}</td><td class="num">${fmt(lp.gap_m, 3)}</td><td class="num">${fmt(lp.bracket_m)}</td><td class="num">${lp.lines_present.length}</td><td>${esc(lp.reason)}</td></tr>`).join("")}</table>
  <h3>Rules &amp; flags</h3>${L.violations.length ? `<ul class="flags">${L.violations.map((v) => `<li class="sev-${esc(v.severity)}"><b>${esc(v.severity)}</b> [${esc(v.rule)}] ${esc(v.message)}</li>`).join("")}</ul>` : "<p class='muted'>No rule violations.</p>"}
  <h3>Bill of materials</h3><table><tr><th>Code</th><th>Description</th><th>Role</th><th class="num">Qty</th><th class="num">Unit kg</th><th class="num">Total kg</th><th>Status</th><th>Source</th></tr>
  ${res.bom.map((b) => `<tr class="${b.status === "estimate" ? "est" : ""}"><td>${esc(b.code)}</td><td>${esc(b.name)}</td><td>${esc(b.role)}</td><td class="num">${b.qty}</td><td class="num">${fmt(b.unit_weight_kg)}</td><td class="num">${fmt(b.total_weight_kg, 1)}</td><td>${esc(b.status)}</td><td class="small-print">${esc(b.source)} · ${esc(b.catalogue)} ${esc(b.catalogue_version)}</td></tr>`).join("")}
  <tr><th colspan="5">Total</th><th class="num">${fmt(tot, 1)} kg</th><th colspan="2" class="small-print">highlighted = estimate weight</th></tr></table>`;
}

/* ---------------------------------------------------------------- drawing: section + elevation */
function extents(run) {
  const systems = Object.keys(run.results), sec = run.section, mir = run.results[systems[0]].layout.mirrored;
  const a = run.snapshot.area;
  let ys = [], zs = [a.z_base, a.z_base + 2 * Math.max(...systems.map((s) => run.results[s].layout.n_lifts)) + 1.2];
  if (sec) for (const [y, z] of sec.points) if (z >= a.z_base - 1 && z <= zs[1] + 1) ys.push(mir ? -y : y);
  for (const s of systems) { const L = run.results[s].layout; ys.push(...L.line_y); L.lifts.forEach((lp) => { if (lp.edge_y !== null) ys.push(lp.edge_y); if (lp.hull_y !== null) ys.push(lp.hull_y); }); }
  return { y0: Math.min(...ys) - 0.6, y1: Math.max(...ys) + 0.9, z0: zs[0] - 0.4, z1: zs[1] + 0.4, mir };
}
function sectionSvg(run, s) {
  const E = extents(run), W = 520, H = 560, a = run.snapshot.area, L = run.results[s].layout;
  const sc = Math.min(W / (E.y1 - E.y0), H / (E.z1 - E.z0));
  const X = (y) => ((y - E.y0) * sc).toFixed(1), Y = (z) => ((E.z1 - z) * sc).toFixed(1);
  const w = ((E.y1 - E.y0) * sc).toFixed(0), hgt = ((E.z1 - E.z0) * sc).toFixed(0);
  const g = []; const tag = (lift, ph, inner) => `<g data-lift="${lift}" data-ph="${ph}">${inner}</g>`;
  // hull
  if (run.section) g.push(`<polyline points="${run.section.points.map(([y, z]) => `${X(E.mir ? -y : y)},${Y(z)}`).join(" ")}" fill="none" stroke="#475569" stroke-width="3"/>`);
  (a.obstructions || []).forEach((o) => g.push(`<polygon points="${o.points.map(([y, z]) => `${X(E.mir ? -y : y)},${Y(z)}`).join(" ")}" fill="#c084fc" fill-opacity=".5" stroke="#7e22ce"><title>${esc(o.name)}</title></polygon>`));
  g.push(`<line x1="0" x2="${w}" y1="${Y(a.z_base)}" y2="${Y(a.z_base)}" stroke="#94a3b8" stroke-dasharray="4 3"/>`);
  const zk = (k) => L.z_base + 2 * k;
  L.line_y.forEach((y, j) => {
    const top = L.line_top_lift[j];
    g.push(tag(0, PHASE.base_jack, `<rect x="${X(y) - 3}" y="${Y(L.z_base)}" width="6" height="4" fill="#334155"/>`));
    for (let k = 1; k <= top; k++) g.push(tag(k - 1, PHASE.standard, `<line x1="${X(y)}" x2="${X(y)}" y1="${Y(zk(k - 1))}" y2="${Y(zk(k))}" stroke="#334155" stroke-width="2"/>`));
    g.push(tag(top, PHASE.standard, `<line x1="${X(y)}" x2="${X(y)}" y1="${Y(zk(top))}" y2="${Y(zk(top) + (j === 0 ? 1 : 0.5))}" stroke="#334155" stroke-width="2"/>`));
  });
  L.lifts.forEach((lp) => {
    const z = lp.z_deck, yo = L.line_y[0], yi = L.line_y[lp.inner_line], ye = lp.edge_y ?? yi;
    g.push(tag(lp.k, PHASE.transom, `<line x1="${X(yi)}" x2="${X(yo)}" y1="${Y(z)}" y2="${Y(z)}" stroke="#64748b" stroke-width="1.5"/>`));
    if (lp.bracket_m) g.push(tag(lp.k, PHASE.bracket, `<line x1="${X(ye)}" x2="${X(yi)}" y1="${Y(z)}" y2="${Y(z)}" stroke="#ea580c" stroke-width="4"/><line x1="${X(yi)}" x2="${X(ye + 0.05)}" y1="${Y(z - 0.45)}" y2="${Y(z)}" stroke="#ea580c" stroke-width="1.5"/>`));
    if (lp.decked) g.push(tag(lp.k, PHASE.deck, `<line x1="${X(lp.bracket_m ? ye : yi)}" x2="${X(yo)}" y1="${Y(z) - 2}" y2="${Y(z) - 2}" stroke="#a16207" stroke-width="4"/>`));
    if (lp.decked) g.push(tag(lp.k, PHASE.guardrail, `<line x1="${X(yo) + 4}" x2="${X(yo) + 4}" y1="${Y(z)}" y2="${Y(z + 1)}" stroke="#16a34a" stroke-width="1.5"/><line x1="${X(yo)}" x2="${X(yo) + 9}" y1="${Y(z + 0.5)}" y2="${Y(z + 0.5)}" stroke="#16a34a"/><line x1="${X(yo)}" x2="${X(yo) + 9}" y1="${Y(z + 1)}" y2="${Y(z + 1)}" stroke="#16a34a"/>`));
    if (lp.status === "infill" && lp.hull_y !== null) g.push(tag(lp.k, PHASE.infill, `<rect x="${X(lp.hull_y + a.clearance_target_m)}" y="${Y(z) - 4}" width="${Math.max(2, (ye - lp.hull_y - a.clearance_target_m) * sc).toFixed(1)}" height="6" fill="#dc2626"><title>Infill ${fmt(lp.infill_width_m, 3)} m</title></rect>`));
    const col = lp.status === "infill" ? "#dc2626" : lp.status === "bracket" ? "#a16207" : lp.status === "open" ? "#64748b" : "#15803d";
    g.push(`<text x="${(+X(yo) + 14).toFixed(1)}" y="${(+Y(z) + 4).toFixed(1)}" font-size="11" fill="${col}">L${lp.k} ${lp.gap_m !== null ? fmt(lp.gap_m, 2) + " m" : lp.status}</text>`);
    g.push(`<text x="2" y="${(+Y(z) + 4).toFixed(1)}" font-size="10" fill="#94a3b8">z ${fmt(z, 1)}</text>`);
  });
  const fr = run.snapshot.geometry.frame;
  g.push(`<text x="6" y="14" font-size="12" fill="#0f172a">${fr !== null ? "FR " + esc(fr) + " · " : ""}${esc(a.side || "")} · ${esc(L.mode)} · widths ${L.widths.map((x) => x.toFixed(2)).join("/")}</text>`);
  return `<svg viewBox="0 0 ${+w + 60} ${hgt}" data-sys="${esc(s)}" class="anim">${g.join("")}</svg>`;
}
function elevationSvg(run, s) {
  const L = run.results[s].layout, a = run.snapshot.area;
  const len = Math.max(L.run_covered_m, L.run_target_m) + 0.6, Hm = 2 * L.n_lifts + 1.2;
  const W = 520, sc = Math.min(W / len, 220 / Hm), X = (x) => (x * sc + 10).toFixed(1), Y = (z) => ((Hm - z) * sc + 6).toFixed(1);
  const tag = (lift, ph, inner) => `<g data-lift="${lift}" data-ph="${ph}">${inner}</g>`;
  const posts = [0]; L.bays.forEach((b) => posts.push(posts[posts.length - 1] + b));
  const g = [];
  g.push(`<rect x="${X(0)}" y="${Y(2 * L.n_lifts)}" width="${(L.run_target_m * sc).toFixed(1)}" height="${(2 * L.n_lifts * sc).toFixed(1)}" fill="#e2e8f0"/>`);
  const T0 = L.line_top_lift[0];
  posts.forEach((x) => { for (let k = 1; k <= T0; k++) g.push(tag(k - 1, PHASE.standard, `<line x1="${X(x)}" x2="${X(x)}" y1="${Y(2 * (k - 1))}" y2="${Y(2 * k)}" stroke="#334155" stroke-width="1.5"/>`)); });
  L.lifts.forEach((lp) => {
    const z = 2 * lp.k;
    L.bays.forEach((b, i) => {
      g.push(tag(lp.k, PHASE.ledger, `<line x1="${X(posts[i])}" x2="${X(posts[i + 1])}" y1="${Y(z)}" y2="${Y(z)}" stroke="#64748b"/>`));
      if (i % 5 === 0) g.push(tag(lp.k, PHASE.diagonal, `<line x1="${X(posts[i])}" x2="${X(posts[i + 1])}" y1="${Y(z - 2)}" y2="${Y(z)}" stroke="#94a3b8"/>`));
      if (lp.decked) g.push(tag(lp.k, PHASE.deck, `<line x1="${X(posts[i])}" x2="${X(posts[i + 1])}" y1="${(+Y(z) - 2).toFixed(1)}" y2="${(+Y(z) - 2).toFixed(1)}" stroke="#a16207" stroke-width="3"/>`));
      if (lp.decked) g.push(tag(lp.k, PHASE.guardrail, `<line x1="${X(posts[i])}" x2="${X(posts[i + 1])}" y1="${Y(z + 1)}" y2="${Y(z + 1)}" stroke="#16a34a"/>`));
    });
    if (lp.status === "infill") g.push(tag(lp.k, PHASE.infill, `<rect x="${X(0)}" y="${(+Y(z) - 5).toFixed(1)}" width="${(L.run_covered_m * sc).toFixed(1)}" height="4" fill="#dc2626" opacity=".8"><title>transverse infill lift ${lp.k}</title></rect>`));
    if (L.longitudinal_infill) g.push(tag(lp.k, PHASE.infill, `<rect x="${X(L.run_covered_m)}" y="${Y(z)}" width="${(L.run_residual_m * sc).toFixed(1)}" height="${(1 * sc).toFixed(1)}" fill="#dc2626"><title>longitudinal infill ${fmt(L.run_residual_m)} m</title></rect>`));
  });
  g.push(`<line x1="${X(L.run_target_m)}" x2="${X(L.run_target_m)}" y1="${Y(0)}" y2="${Y(Hm - 0.3)}" stroke="#0f172a" stroke-dasharray="3 3"/>`);
  const ff = a.frame_from, sp = a.frame_spacing_m || 0.7;
  if (ff !== null && ff !== undefined) posts.forEach((x, i) => { if (i % Math.max(1, Math.round(posts.length / 8)) === 0 || i === posts.length - 1) g.push(`<text x="${X(x)}" y="${(+Y(0) + 11).toFixed(1)}" font-size="9" text-anchor="middle" fill="#475569">Fr ${fmt(ff + x / sp, 1)}</text>`); });
  g.push(`<text x="${X(0)}" y="${(+Y(0) + 22).toFixed(1)}" font-size="10" fill="#0f172a">${L.bays.length} bays: ${L.bays.map((b) => b.toFixed(2)).join(" + ")} = ${fmt(L.run_covered_m)} m (run ${fmt(L.run_target_m)} m, ends ${esc(L.run_start)}/${esc(L.run_end)})</text>`);
  return `<svg viewBox="0 0 ${W + 20} ${(Hm * sc + 36).toFixed(0)}" class="anim" data-sys="${esc(s)}">${g.join("")}</svg>`;
}

/* ---------------------------------------------------------------- animation */
function setupPlayer(run, maxMin) {
  const systems = Object.keys(run.results);
  const steps = Object.fromEntries(systems.map((s) => [s, run.results[s].simulation.steps]));
  const area = run.snapshot.area;
  const update = (t) => {
    $("#tlabel").textContent = `t = ${fmt(t, 1)} min`;
    for (const s of systems) {
      const st = steps[s]; let done = -1;
      for (let i = 0; i < st.length; i++) { if (st[i].cum_elapsed_min <= t + 1e-9) done = i; else break; }
      const cur = done >= 0 ? st[done] : null;
      const key = cur ? cur.lift * 100 + (PHASE[cur.phase] ?? 99) : -1;
      $$(`svg.anim[data-sys="${s}"] g[data-lift]`).forEach((el) => { el.style.display = (+el.dataset.lift * 100 + +el.dataset.ph) <= key ? "" : "none"; });
      const infills = st.slice(0, done + 1).filter((x) => x.action === "infill").reduce((a, b) => a + b.qty, 0);
      const L = run.results[s].layout; const liftsDone = cur ? (st.slice(done + 1).some((x) => x.lift === cur.lift) ? cur.lift - 1 : cur.lift) : 0;
      const m2 = Math.max(0, liftsDone) * 2 * L.run_target_m;
      $(`#cnt-${s}`).innerHTML = `<div>crew-h<b>${fmt(cur ? cur.cum_crew_h : 0, 1)}</b></div><div>elapsed<b>${fmt(cur ? cur.cum_elapsed_min : 0, 0)} min</b></div><div>m² ready<b>${fmt(m2, 0)}</b></div><div>infill units<b>${infills}</b></div>`;
    }
  };
  const scrub = $("#scrub");
  scrub.oninput = () => update(+scrub.value);
  let playing = false, last = 0;
  state.anim = { raf: 0 };
  const tick = (ts) => { if (!playing) return; const dt = last ? (ts - last) / 1000 : 0; last = ts; let t = +scrub.value + dt * (+$("#speed").value) / 60; /* sim min = real s x speed / 60 */ if (t >= maxMin) { t = maxMin; playing = false; $("#play").textContent = "▶ Play"; } scrub.value = t; update(t); state.anim.raf = requestAnimationFrame(tick); };
  $("#play").onclick = () => { playing = !playing; $("#play").textContent = playing ? "❚❚ Pause" : "▶ Play"; if (playing) { if (+scrub.value >= maxMin) scrub.value = 0; last = 0; state.anim.raf = requestAnimationFrame(tick); } };
  update(maxMin);
}

/* ---------------------------------------------------------------- drawings tab */
function miniSection(sec) {
  if (!sec || !sec.points?.length) return "";
  const ys = sec.points.map((p) => p[0]), zs = sec.points.map((p) => p[1]);
  const y0 = Math.min(0, ...ys), y1 = Math.max(...ys) + 0.5, z0 = Math.min(...zs) - 0.5, z1 = Math.max(...zs) + 0.5;
  const sc = Math.min(220 / (y1 - y0), 170 / (z1 - z0));
  return `<svg viewBox="0 0 230 180"><line x1="${((0 - y0) * sc + 5).toFixed(1)}" x2="${((0 - y0) * sc + 5).toFixed(1)}" y1="0" y2="180" stroke="#22c55e" stroke-dasharray="3 3"/><polyline fill="none" stroke="#334155" stroke-width="2" points="${sec.points.map(([y, z]) => `${((y - y0) * sc + 5).toFixed(1)},${((z1 - z) * sc + 5).toFixed(1)}`).join(" ")}"/></svg>`;
}
function manualSection() {
  const pts = $("#msPts").value.trim().split(/\n+/).map((l) => l.split(/[,;\s]+/).map(Number)).filter((p) => p.length >= 2 && !p.some(isNaN)).map((p) => [p[0], p[1]]);
  return { id: $("#msId").value, frame: +$("#msFrame").value, x: +$("#msFrame").value * (state.project.frame_spacing_m || 0.7), points: pts, source: "manual", confidence: "low", notes: ["manual input — verify against drawing"] };
}
function renderDrawings() {
  const p = state.project;
  $("#sectionGrid").innerHTML = p.sections.map((s) => `<div class="card"><b>${esc(s.id)}</b> · FR ${esc(s.frame)} ${confBadge(s.confidence)}<div class="small-print">${esc(s.source)} ${esc(s.source_file || "")} · ${s.points.length} pts</div>${miniSection(s)}${(s.notes || []).length ? `<div class="small-print sev-warning">${s.notes.map(esc).join("<br>")}</div>` : ""}</div>`).join("") || "<p class='muted'>No sections yet.</p>";
  const dr = p.drawings || [];
  if (!$("#wizard").dataset.active) $("#wizard").innerHTML = dr.length ? `<h3>Uploaded drawings</h3><ul>${dr.map((d) => `<li>${esc(d.file)} (${esc(d.kind)}) ${d.template ? "· template " + esc(d.template) : ""} <button class="small" data-redo="${esc(d.id)}">Mapping wizard</button></li>`).join("")}</ul>` : "";
  $$("[data-redo]").forEach((b) => b.onclick = async () => { const d = (state.project.drawings || []).find((x) => x.id === b.dataset.redo); if (!d.inspect) { toast("Re-upload the file to inspect it again."); return; } renderWizard(d); });
}
async function uploadDrawing() {
  const f = $("#fileIn").files[0]; if (!f) throw new Error("Choose a file first");
  const fd = new FormData(); fd.append("file", f);
  const d = await api(`/api/projects/${state.project.id}/drawings`, { method: "POST", body: fd });
  renderWizard(d);
}
async function renderWizard(d) {
  const meanings = state.meta.meanings, info = d.inspect;
  const templates = await api("/api/mappings");
  const box = $("#wizard"); box.dataset.active = "1";
  const opt = (sel) => meanings.map((m) => `<option ${m === sel ? "selected" : ""}>${m}</option>`).join("");
  if (d.kind === "pdf") {
    const zoom = Math.min(1.0, 1400 / info.size_pt[0]);
    box.innerHTML = `<div class="panel"><h3>PDF style mapping — ${esc(d.file)} (page ${info.page + 1}/${info.pages})</h3>
    ${info.raster_only ? `<div class="warnbox">Raster page (scan): tracing tool is phase 2 — use the manual editor.</div>` : ""}
    <table><tr><th>Style (colour / width)</th><th class="num">Paths</th><th>Meaning</th></tr>${info.styles.map((s) => `<tr><td><span style="display:inline-block;width:14px;height:10px;background:${esc(s.style.split("/")[0])}"></span> ${esc(s.style)}</td><td class="num">${s.paths}</td><td><select data-style="${esc(s.style)}">${opt("ignore")}</select></td></tr>`).join("")}</table>
    <p class="small-print">Calibration: click two points of known distance on the page (e.g. ends of the CL line or a dimension), then a second pair to verify.</p>
    <div class="grid-form"><label>P1 (pt)<input id="c1"></label><label>P2 (pt)<input id="c2"></label><label>Distance (m)<input id="cd" type="number" step="any"></label>
    <label>Verify P1<input id="v1"></label><label>Verify P2<input id="v2"></label><label>Verify distance (m)<input id="vd" type="number" step="any"></label>
    <label class="span2">Frames per view, left → right (if text is vector outlines)<input id="vf" placeholder="${info.frames.length ? "auto from text" : "e.g. 128,140,152"}"></label><label>Template name<input id="tpl"></label></div>
    <div class="row"><span class="muted">Click target:</span><select id="clickTarget"><option value="c1">P1</option><option value="c2">P2</option><option value="v1">Verify P1</option><option value="v2">Verify P2</option></select><button id="doImport" class="primary">Import sections</button><button id="closeWiz" class="small">Close</button></div>
    <div style="overflow:auto;max-height:600px;border:1px solid #ddd"><img id="pdfImg" src="/api/drawings/${esc(d.id)}/page/${info.page}.png?zoom=${zoom}" style="cursor:crosshair;display:block"></div><div id="impOut"></div></div>`;
    $("#pdfImg").onclick = (e) => { const r = e.target.getBoundingClientRect(); const x = (e.clientX - r.left) / zoom, y = (e.clientY - r.top) / zoom; const t = $("#clickTarget"); $("#" + t.value).value = `${x.toFixed(1)},${y.toFixed(1)}`; t.selectedIndex = (t.selectedIndex + 1) % 4; };
    const pt = (id) => $("#" + id).value.split(",").map(Number);
    $("#doImport").onclick = (e) => busy(e.target, async () => {
      const mapping = {}; $$("[data-style]").forEach((s) => mapping[s.dataset.style] = s.value);
      const body = { mapping, page: info.page, template: $("#tpl").value || null, calibration: { p1: pt("c1"), p2: pt("c2"), distance_m: +$("#cd").value } };
      if ($("#vd").value) body.verification = { p1: pt("v1"), p2: pt("v2"), distance_m: +$("#vd").value };
      if ($("#vf").value.trim()) body.view_frames = $("#vf").value.split(",").map(Number);
      const r = await api(`/api/projects/${state.project.id}/drawings/${d.id}/import`, { method: "POST", body });
      $("#impOut").innerHTML = importReport(r); await loadProject(state.project.id, state.areaId);
    });
  } else {
    box.innerHTML = `<div class="panel"><h3>Layer mapping — ${esc(d.file)}</h3>
    <p class="small-print">Units $INSUNITS=${esc(info.insunits)} (${info.unit_to_m ?? "unset"} m per unit). Frames found in text: ${info.frames_found.map(esc).join(", ") || "none"}. Dimensions checked: ${info.dimensions.length}.</p>
    <div class="row"><label>Apply saved template <select id="tplSel"><option value="">—</option>${templates.filter((t) => t.kind !== "pdf").map((t) => `<option>${esc(t.template)}</option>`).join("")}</select></label><label>Save as template <input id="tpl" placeholder="e.g. VARD-DESIGN-SECTIONS"></label></div>
    <table><tr><th>Layer</th><th class="num">Entities</th><th>Types</th><th>Meaning</th></tr>${info.layers.map((l) => `<tr><td>${esc(l.name)}</td><td class="num">${l.entities}</td><td class="small-print">${esc(Object.entries(l.types).map(([k, v]) => k + "×" + v).join(", "))}</td><td><select data-layer="${esc(l.name)}">${opt(l.guess)}</select></td></tr>`).join("")}</table>
    <div class="row"><button id="doImport" class="primary">Import sections</button><button id="closeWiz" class="small">Close</button></div><div id="impOut"></div></div>`;
    $("#tplSel").onchange = () => { const t = templates.find((x) => x.template === $("#tplSel").value); if (t) $$("[data-layer]").forEach((s) => { if (t.mapping[s.dataset.layer]) s.value = t.mapping[s.dataset.layer]; }); };
    $("#doImport").onclick = (e) => busy(e.target, async () => {
      const mapping = {}; $$("[data-layer]").forEach((s) => mapping[s.dataset.layer] = s.value);
      const r = await api(`/api/projects/${state.project.id}/drawings/${d.id}/import`, { method: "POST", body: { mapping, template: $("#tpl").value || null } });
      $("#impOut").innerHTML = importReport(r); await loadProject(state.project.id, state.areaId);
    });
  }
  $("#closeWiz").onclick = () => { delete box.dataset.active; renderDrawings(); };
}
function importReport(r) {
  const rep = r.report;
  return `<div class="warnbox" style="background:#f0fdf4;border-color:#bbf7d0">Imported ${r.sections.length} section(s): ${r.sections.map((s) => `${esc(s.id)} ${confBadge(s.confidence)}`).join(", ")}</div>${(rep.warnings || []).map((w) => `<div class="warnbox">${esc(w)}</div>`).join("")}${rep.verification ? `<p class="small-print">Scale verification error ${fmt(rep.verification.error_pct, 3)}%</p>` : ""}`;
}

/* ---------------------------------------------------------------- summary */
async function renderSummary() {
  const s = await api(`/api/projects/${state.project.id}/summary`);
  const el = $("#summary");
  if (!s.areas.length) { el.innerHTML = "<p class='muted'>No runs yet. Run the areas first.</p>"; return; }
  const pol = Object.entries(s.policies);
  const maxCost = Math.max(...pol.map(([, p]) => p.cost_eur));
  el.innerHTML = `<h2>Vessel summary — ${esc(state.project.name)}</h2>
  <div class="panel"><h3>Policy comparison</h3><table><tr><th>Policy</th><th class="num">Crew-hours</th><th class="num">Peak t*</th><th class="num">Cost EUR</th><th></th><th class="num">of which complexity</th><th class="num">Infill units</th><th class="num">Areas w/ violations</th>${s.systems.map((x) => `<th class="num">share ${esc(x)}</th>`).join("")}</tr>
  ${pol.map(([n, p]) => `<tr class="${n === s.cheapest_policy ? "win" : ""}"><td>${esc(n)}</td><td class="num">${fmt(p.crew_hours, 1)}</td><td class="num">${fmt(p.peak_t, 2)}</td><td class="num">${fmt(p.cost_eur, 0)}</td><td><span class="bar" style="width:${(120 * p.cost_eur / maxCost).toFixed(0)}px"></span></td><td class="num">${fmt(p.complexity_cost_eur, 0)}</td><td class="num">${p.infill_units}</td><td class="num">${p.invalid_areas}</td>${s.systems.map((x) => `<td class="num">${fmt(100 * p.share_by_system[x], 0)}%</td>`).join("")}</tr>`).join("")}</table>
  <p class="small-print">Cheapest: <b>${esc(s.cheapest_policy)}</b>. *${esc(s.assumptions.peak_t)}. Complexity cost of a second system: ${fmt(s.assumptions.complexity_cost_eur_per_year, 0)} EUR/yr × ${s.assumptions.vessel_build_months}/12 months = ${fmt(s.assumptions.complexity_cost_applied_eur, 0)} EUR (applied to mixed policy only).</p>
  <a href="/api/projects/${esc(state.project.id)}/summary/excel"><button>Excel</button></a></div>
  <div class="panel"><h3>Per area</h3><table><tr><th>Area</th><th>Confidence</th><th>Recommended</th><th class="num">Margin %</th>${s.systems.map((x) => `<th class="num">${esc(x)} crew-h</th><th class="num">${esc(x)} t</th><th class="num">${esc(x)} EUR</th><th class="num">${esc(x)} infills</th>`).join("")}</tr>
  ${s.areas.map((a) => `<tr><td>${esc(a.name)}<div class="small-print">${esc(a.area_id)} · run ${esc(a.run_id)}</div></td><td>${confBadge(a.confidence)}</td><td style="color:${sysColor(a.recommended)}"><b>${esc(a.recommended)}</b></td><td class="num">${fmt(a.margin_pct, 1)}</td>${s.systems.map((x) => { const v = a.systems[x] || {}; return `<td class="num">${fmt(v.crew_hours, 1)}</td><td class="num">${fmt(v.weight_t, 2)}</td><td class="num">${fmt(v.total_cost_eur, 0)}</td><td class="num ${v.valid === false ? "sev-error" : ""}">${fmt(v.infill_units, 0)}</td>`; }).join("")}</tr>`).join("")}</table></div>`;
}

/* ---------------------------------------------------------------- catalogues */
async function renderCatalogues() {
  const el = $("#catalogues"); const m = state.meta;
  const parts = [];
  for (const sid of Object.keys(m.catalogues)) {
    const [c, t] = await Promise.all([api(`/api/catalogues/${sid}`), api(`/api/time-standards/${sid}`)]);
    parts.push(`<div class="panel"><h3 style="color:${sysColor(sid)}">${esc(c.name)} <span class="muted">${esc(c.file)} · v${esc(c.catalogue_version)} · <code>${esc(c.sha256)}</code></span></h3>
    <p class="small-print">Node: ${esc(JSON.stringify(c.node))} · bays ${c.bay_lengths_m.join(" / ")} m · widths ${c.bay_widths_m.join(" / ")} m · lift ${c.lift_height_m} m · source: ${esc(c.default_source)}</p>
    <details><summary>Rules</summary><table><tr><th>Rule</th><th>Value</th><th>Status</th><th>Source</th></tr>${Object.entries(c.rules).map(([k, r]) => `<tr class="${r.status === "estimate" ? "est" : ""}"><td>${esc(k)}</td><td>${esc(JSON.stringify(r.value))}</td><td>${esc(r.status)}</td><td class="small-print">${esc(r.source)}</td></tr>`).join("")}</table></details>
    <details><summary>Components (${c.components.length})</summary><table><tr><th>Code</th><th>Name</th><th>Role</th><th class="num">L (m)</th><th class="num">kg</th><th>Status</th></tr>${c.components.map((x) => `<tr class="${x.status === "estimate" ? "est" : ""}"><td>${esc(x.code)}</td><td>${esc(x.name)}</td><td>${esc(x.role)}</td><td class="num">${x.length_m}</td><td class="num">${x.weight_kg}</td><td>${esc(x.status)}</td></tr>`).join("")}</table></details>
    <details><summary>Time standard ${esc(t.version)} [${esc(t.status)}]</summary><p class="small-print">${esc(t.derivation)}</p><table><tr><th>Action</th><th class="num">Base weight</th><th class="num">Man-seconds</th></tr>${Object.entries(t.actions).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${t.base_weights[k] ?? ""}</td><td class="num">${fmt(v, 1)}</td></tr>`).join("")}<tr><td>infill (per unit)</td><td></td><td class="num">${t.infill_crew_hours_per_unit} crew-h</td></tr></table></details></div>`);
  }
  el.innerHTML = `<h2>Catalogues &amp; time standards</h2><p class="muted">Add a system by dropping a catalogue YAML in <code>data/catalogues/</code> (and optionally a time standard in <code>data/time_standards/</code>). No code changes. Highlighted rows are <b>estimates</b>.</p>${parts.join("")}`;
}

init().catch((e) => toast(e.message, true));
