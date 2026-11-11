// AeroSim Workbench – front end (ANSYS-style: Outline / Details / Graphics / Messages)
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 4) => (v === null || v === undefined || v === "" || Number.isNaN(+v)) ? "—"
  : (Math.abs(+v) >= 1e5 || (Math.abs(+v) < 1e-3 && +v !== 0)) ? (+v).toExponential(3) : (+(+v).toPrecision(d)).toString();

// Read-only demo mode (static snapshot of a finished case, no server)
const DEMO = window.AEROSIM_DEMO || null;
function notify(msg, err) {
  const el = $("#statusText"); if (!el) return;
  el.textContent = msg; el.style.color = err ? "var(--err)" : "";
  clearTimeout(notify.t); notify.t = setTimeout(() => { el.style.color = ""; }, 8000);
}
const DEMO_MSG = "Read-only demo: install AeroSim Workbench on your computer to change inputs and run solvers.";
async function demoApi(path, opts) {
  if (opts.method === "POST") throw new Error(DEMO_MSG);
  const u = new URL(path, location.href), parts = u.pathname.split("/").filter(Boolean);
  const i = parts.indexOf("api");
  const p = parts.slice(i + 1);
  if (p[0] === "cases") return DEMO.cases;
  const what = p[2] || "state";
  if (what === "state") return DEMO.state;
  if (what === "log") return { text: +u.searchParams.get("from") ? "" : DEMO.log, next: 1 };
  if (what === "history") return fetch(DEMO.base + "history.json").then((r) => r.json());
  return {};
}
async function api(path, opts = {}) {
  if (DEMO) return demoApi(path, opts);
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// --------------------------------------------------------------------------- state
const RATE = {};
let cid = null, ST = null, sel = "geometry", logPos = 0, lastSig = "", pollT = null;
const fileURL = (rel, bust) => DEMO ? DEMO.base + rel : `/files/${encodeURIComponent(cid)}/${rel}${bust ? "?v=" + encodeURIComponent(bust) : ""}`;

const RESULT_NAMES = {
  contour_mach: "Mach Number", contour_pressure: "Static Pressure", contour_cp: "Pressure Coefficient", contour_pressure_coefficient: "Pressure Coefficient", contour_speed: "Velocity Magnitude",
  contour_mach_wake: "Mach Number – Wake", cp_surface: "Cp Distribution", cf_yplus: "Skin Friction & y+",
  convergence: "Convergence History", mesh: "Mesh (near wall)", surface_cp_top: "Surface Cp – Upper",
  surface_cp_bottom: "Surface Cp – Lower", streamlines_3d: "Streamlines", cp_sections: "Cp at Span Stations",
  span_loading: "Spanwise Loading", stress_von_mises: "Equivalent Stress (image)", displacement: "Total Deformation (image)",
  strain: "Equivalent Strain (image)",
};
const resName = (rel) => {
  const b = rel.split("/").pop().replace(".png", "");
  if (RESULT_NAMES[b]) return RESULT_NAMES[b];
  const m = b.match(/^(\w+)_slice_eta(\d+)/);
  if (m) return `${m[1][0].toUpperCase() + m[1].slice(1)} Slice  η = ${(+m[2] / 100).toFixed(2)}`;
  return b.replace(/_/g, " ");
};

// --------------------------------------------------------------------------- outline tree
const STATUS_ICON = { ok: "✔", stale: "⚡", none: "?", error: "✖", running: "◌", queued: "⧗", skipped: "–" };
function stepStatus(s) {
  if (!ST) return "none";
  if (ST.queued?.includes(s)) return "queued";
  return ST.steps[s]?.status || "none";
}
function buildTree() {
  if (!ST) { $("#tree").innerHTML = ""; return; }
  const dv = ST.derived, res = ST.steps.results?.info || {}, fea = ST.steps.structure?.info || {};
  const resKids = [];
  if (res.viewer) resKids.push({ id: "res3d", ic: "🌈", label: "Surface Pressure (3D)", step: "results" });
  (res.images || []).filter(r => !/convergence|\/mesh\.png/.test(r)).forEach((r) =>
    resKids.push({ id: "img:" + r, ic: "🖼", label: resName(r), step: "results" }));
  const feaKids = [];
  if (fea.viewer) {
    feaKids.push({ id: "fea:von Mises [MPa]", ic: "🌈", label: "Equivalent Stress", step: "structure" });
    feaKids.push({ id: "fea:|u| [mm]", ic: "🌈", label: "Total Deformation", step: "structure" });
    feaKids.push({ id: "fea:equiv. strain [µε]", ic: "🌈", label: "Equivalent Strain", step: "structure" });
  }
  const nodes = [
    { id: "project", ic: "📁", label: `Project – ${ST.settings.name}`, open: true, kids: [
      { id: "model", ic: "✈", label: `Model (${dv.dim}D${dv.dim === 3 ? (dv.half ? ", half" : ", full") : ""})`, open: true, kids: [
        { id: "geometry", ic: "🧊", label: "Geometry", step: "geometry" },
        { id: "conditions", ic: "🌬", label: "Flow Conditions", step: "conditions" },
        { id: "references", ic: "📐", label: "Reference Values", step: "setup" },
        { id: "mesh", ic: "▦", label: "Mesh", step: "mesh" },
      ]},
      { id: "fluid", ic: "💨", label: `Fluid Flow (SU2 ${dv.solver}${dv.viscous ? " " + dv.turb : ""})`, open: true, kids: [
        { id: "setup", ic: "⚙", label: "Analysis Settings", step: "setup" },
        { id: "solve", ic: "🧮", label: "Solution", step: "solve", open: true, kids: [
          { id: "solinfo", ic: "📈", label: "Solution Information", step: "solve" },
          { id: "results", ic: "📊", label: "Results & Checks", step: "results", open: true, kids: resKids },
          { id: "polar", ic: "📉", label: "Polar Sweep (α)", step: "polar" },
        ]},
      ]},
      ...(dv.dim === 3 ? [{ id: "structural", ic: "🏗", label: "Static Structural (CalculiX)", step: "structure", open: true, kids: [
        { id: "structure", ic: "⚙", label: "Analysis Settings", step: "structure" },
        { id: "feasol", ic: "🧮", label: "Solution", step: "structure", open: true, kids: feaKids },
      ]}] : []),
      { id: "report", ic: "📑", label: "Report", step: "report" },
      { id: "handoff", ic: "📦", label: "Handoff Package", step: "handoff" },
    ]},
  ];
  const html = (list) => `<ul class="tree">${list.map((n) => {
    const st = n.step ? stepStatus(n.step) : null;
    const hasK = n.kids && n.kids.length;
    return `<li><div class="node${n.id === sel ? " sel" : ""}" data-id="${esc(n.id)}">
      <span class="tw">${hasK ? "▾" : ""}</span><span class="ic">${n.ic}</span>
      ${st ? `<span class="st ${st}" title="${st}">${STATUS_ICON[st]}</span>` : ""}
      <span class="lb">${esc(n.label)}</span></div>${hasK ? html(n.kids).replace('<ul class="tree">', "<ul>") : ""}</li>`;
  }).join("")}</ul>`;
  $("#tree").innerHTML = html(nodes);
  $$("#tree .node").forEach((el) => el.onclick = () => select(el.dataset.id));
}

// --------------------------------------------------------------------------- details panel
const S = () => ST.settings;
const get = (path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), ST.settings);

function row(def) {
  if (def.sec) return `<tr class="sec"><td colspan=2>${esc(def.sec)}</td></tr>`;
  const label = esc(def.k) + (def.unit ? ` <span class="unit">[${esc(def.unit)}]</span>` : "");
  if ("ro" in def) return `<tr><td class="k">${label}</td><td class="ro" title="${esc(def.ro)}">${esc(def.ro)}</td></tr>`;
  const v = get(def.path);
  let ctl;
  if (def.type === "select") {
    ctl = `<select data-path="${def.path}" data-type="${def.num ? "num" : "str"}">${def.opts.map(([val, lab]) =>
      `<option value="${esc(val)}"${String(v) === String(val) ? " selected" : ""}>${esc(lab)}</option>`).join("")}</select>`;
  } else {
    ctl = `<input data-path="${def.path}" data-type="${def.type || "num"}" value="${v === null || v === undefined ? "" : esc(v)}"
      placeholder="${esc(def.ph ?? "")}" ${def.type === "text" ? "" : 'inputmode="decimal"'}>`;
  }
  return `<tr class="${v === null || v === "" || v === "auto" ? "" : ""}"><td class="k">${label}</td><td>${ctl}</td></tr>`;
}
const grid = (defs) => `<table class="grid">${defs.filter(Boolean).map(row).join("")}</table>`;
const note = (txt, cls = "") => `<div class="dnote ${cls}">${txt}</div>`;
const actions = (btns) => `<div class="dact">${btns.join("")}</div>`;
const updBtn = (step, label = "Update") => `<button class="primary" data-upto="${step}">⚡ ${label}</button>`;
const checksHtml = (list) => (list || []).map((c) =>
  `<div class="check"><span class="st ${c.ok ? "ok" : c.ok === null ? "stale" : "error"}">${c.ok ? "✔" : c.ok === null ? "!" : "✖"}</span>
   <div><b>${esc(c.name)}</b><br>${esc(c.detail)}</div></div>`).join("");
function stepNote(step) {
  const e = ST.steps[step];
  if (!e) return note("Not yet run.");
  if (e.status === "error") return note("✖ " + esc(e.error || "failed"), "err");
  if (e.status === "stale") return note("⚡ Inputs changed since the last run — update to refresh.", "warn");
  if (e.status === "running") return note("◌ Running…");
  if (e.status === "skipped") return note("Skipped: " + esc(e.info?.reason || ""));
  return note(`✔ Up to date (${e.finished || ""}${e.seconds != null ? `, ${e.seconds} s` : ""}).`);
}

function details() {
  const box = $("#details");
  if (!ST) { box.innerHTML = note("Create or open a project."); return; }
  const dv = ST.derived, g = S().geometry, n = sel;
  let title = "Details", h = "";
  const notesList = (arr) => arr?.length ? note("<ul>" + arr.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>") : "";

  if (n === "project" || n === "model") {
    title = "Details of \"Project\"";
    h = grid([{ sec: "Project" }, { k: "Name", path: "name", type: "text" }, { ro: ST.settings.created, k: "Created" },
      { sec: "Analysis type" }, { k: "Dimension", ro: dv.dim + "D" }, { k: "Regime", ro: dv.regime || "—" },
      { k: "Flow solver", ro: `SU2 ${dv.solver}${dv.viscous ? " / " + dv.turb : ""}` },
      { k: "Structure", ro: dv.structure ? "CalculiX linear static" : "—" }]) +
      actions([updBtn("", "Update All")]) + notesList(dv.notes);
  } else if (n === "geometry") {
    title = "Details of \"Geometry\"";
    const info = ST.steps.geometry?.info || {};
    const src = g.source;
    h = grid([
      { sec: "Definition" },
      { k: "Source", path: "geometry.source", type: "select", opts: [["naca_wing", "Parametric wing (3D)"], ["naca2d", "NACA airfoil (2D)"], ["cad", "Imported CAD (3D)"], ["dat2d", "Imported .dat airfoil (2D)"]] },
      ...(src === "cad" || src === "dat2d" ? [{ k: "File", ro: (g.cad_file || "— use Import —").split("/").pop() }] : []),
      ...(src.startsWith("naca") ? [{ k: "NACA 4-digit", path: "geometry.naca", type: "text" }] : []),
      ...(src !== "cad" ? [{ k: src === "naca_wing" ? "Root chord" : "Chord", path: "geometry.chord", unit: "m" }] : []),
      ...(src === "naca_wing" ? [{ k: "Taper ratio", path: "geometry.taper" }, { k: "Semispan", path: "geometry.semispan", unit: "m" },
        { k: "LE sweep", path: "geometry.sweep", unit: "°" }, { k: "Dihedral", path: "geometry.dihedral", unit: "°" },
        { k: "Tip twist (−ve washout)", path: "geometry.twist", unit: "°" }] : []),
      ...(src === "cad" ? [{ k: "CAD units", path: "geometry.units", type: "select", opts: [["auto", "Auto (mm if > 50 units)"], ["m", "Metres"], ["mm", "Millimetres"]] },
        { k: "Half model (symmetry y = 0)", path: "geometry.half", type: "select", opts: [["auto", "Auto (if cut on y = 0)"], ["yes", "Yes"], ["no", "No – full body"]] }] : []),
      { sec: "Properties" },
      ...(info.bbox ? [{ k: "Bounding box", ro: `${fmt(info.bbox[3] - info.bbox[0], 3)} × ${fmt(info.bbox[4] - info.bbox[1], 3)} × ${fmt(info.bbox[5] - info.bbox[2], 3)}` },
        { k: "Solids", ro: info.n_solids }, { k: "Projected area", ro: fmt(info.projected_area) + " (CAD units²)" }] : []),
      ...(info.t_over_c ? [{ k: "Section t/c", ro: (info.t_over_c * 100).toFixed(1) + " %" }] : []),
      ...(dv.aspect_ratio ? [{ k: "Aspect ratio (full span)", ro: fmt(dv.aspect_ratio, 3) }] : []),
      ...(dv.mac ? [{ k: "MAC", ro: fmt(dv.mac) + " m" }] : []),
    ]) + actions([updBtn("geometry"), `<button data-import>📂 Import file…</button>`]) + stepNote("geometry") +
      (info.note ? note(esc(info.note), "warn") : "");
  } else if (n === "conditions") {
    title = "Details of \"Flow Conditions\"";
    const c = ST.steps.conditions?.info?.cond;
    const fc = S().conditions;
    h = grid([
      { sec: "Freestream (ISA)" },
      { k: "Altitude", path: "conditions.alt", unit: "m" },
      { k: "Specify by", path: "conditions.spec", type: "select", opts: [["mach", "Mach number"], ["speed", "True airspeed"]] },
      fc.spec === "mach" ? { k: "Mach", path: "conditions.mach" } : { k: "Speed", path: "conditions.speed", unit: "m/s" },
      { k: "Angle of attack", path: "conditions.aoa", unit: "°" },
      ...(dv.dim === 3 ? [{ k: "Sideslip", path: "conditions.beta", unit: "°" }] : []),
      { k: "Temperature override", path: "conditions.T_override", unit: "K", ph: "ISA" },
      { k: "Polar α list (optional)", path: "conditions.polar", type: "text", unit: "°", ph: "e.g. 0, 2, 4, 6, 8" },
      ...(c ? [{ sec: "Computed (flow_conditions.py)" },
        { k: "Mach", ro: fmt(c.mach) }, { k: "Speed", ro: fmt(c.speed_mps) + " m/s" }, { k: "Static T", ro: fmt(c.T_K) + " K" },
        { k: "Static p", ro: fmt(c.p_Pa, 6) + " Pa" }, { k: "Density", ro: fmt(c.rho) + " kg/m³" },
        { k: "Viscosity (Sutherland)", ro: fmt(c.mu) + " Pa·s" }, { k: "Dynamic pressure", ro: fmt(c.q_Pa, 5) + " Pa" },
        { k: "Reynolds (c_ref)", ro: fmt(c.reynolds) }, { k: "Regime", ro: c.regime },
        { k: `First cell for y+ = ${c.target_yplus}`, ro: fmt(c.first_cell_height_m, 3) + " m" }] : []),
    ]) + actions([updBtn("conditions")]) + stepNote("conditions");
  } else if (n === "references") {
    title = "Details of \"Reference Values\"";
    h = grid([{ sec: "Force & moment references" },
      { k: "Reference length c_ref", path: "references.lref", unit: "m", ph: fmt(dv.lref) + " (auto)" },
      { k: "Reference area S_ref", path: "references.sref", unit: "m²", ph: fmt(dv.sref) + " (auto)" },
      { k: "Moment point x", path: "references.xmom", unit: "m", ph: fmt(dv.xmom) + " (auto)" },
    ]) + notesList(dv.notes.filter((x) => /S_ref|reference|References|c_ref/.test(x)));
  } else if (n === "mesh") {
    title = "Details of \"Mesh\"";
    const mi = ST.steps.mesh?.info || {};
    h = grid([{ sec: "Sizing" },
      { k: "Level", path: "mesh.level", type: "select", opts: [["auto", `Auto (${dv.dim === 2 ? "medium" : "coarse"})`], ["coarse", "Coarse"], ["medium", "Medium"], ["fine", "Fine"]] },
      ...(dv.dim === 2 ? [{ k: "First cell height", path: "mesh.y1", unit: "m", ph: "auto: y+ = 1" }]
        : [{ k: "Wall cell size", path: "mesh.wall_h", unit: "m", ph: dv.viscous ? "auto: y+ ≈ 50" : "auto (curvature)" },
           { k: "Cell budget (max cells)", path: "mesh.max_cells" }]),
      { k: "Far-field distance", path: "mesh.farfield", unit: dv.dim === 2 ? "chords" : "c_ref", ph: dv.dim === 2 ? "100" : "12" },
      { sec: "Statistics" },
      { k: "Cells", ro: mi.n_cells ? mi.n_cells.toLocaleString() : "—" },
      { k: "Points", ro: mi.n_points ? mi.n_points.toLocaleString() : "—" },
      ...Object.entries(mi.cells || {}).map(([k, v]) => ({ k: "  " + k, ro: v.toLocaleString() })),
      ...Object.entries(mi.markers || {}).map(([k, v]) => ({ k: "Marker: " + k, ro: v.toLocaleString() + " faces" })),
    ]) + actions([updBtn("mesh", "Generate Mesh")]) + stepNote("mesh") +
      note(dv.dim === 2 ? "Quad boundary layer (y+ ≈ 1) + triangles, circular far field (mesh_2d_airfoil.py)."
        : "Tetrahedra refined toward the wall (mesh_3d.py). The wall layer is not resolved: use Euler, or RANS with wall functions.");
  } else if (n === "setup" || n === "fluid") {
    title = "Details of \"Analysis Settings\" (SU2)";
    h = grid([{ sec: "Physics" },
      { k: "Solver", path: "solver.solver", type: "select", opts: [["auto", `Auto → ${dv.solver}`], ["EULER", "Euler (inviscid)"], ["RANS", "RANS"], ["INC_EULER", "Incompressible Euler"], ["INC_RANS", "Incompressible RANS"], ["NAVIER_STOKES", "Laminar Navier–Stokes"]] },
      ...(dv.viscous ? [{ k: "Turbulence model", path: "solver.turb", type: "select", opts: [["SA", "Spalart–Allmaras"], ["SST", "k-ω SST"]] }] : []),
      ...(dv.viscous && dv.dim === 3 ? [{ k: "Wall functions", path: "solver.wall_functions", type: "select", opts: [["auto", "Auto (on for 3D)"], ["no", "Off"]] }] : []),
      { sec: "Solver controls" },
      { k: "Max iterations", path: "solver.iterations", ph: dv.iterations + " (auto)" },
      { k: "Residual target (log10)", path: "solver.resmin", ph: "-8" },
      { k: "Start CFL", path: "solver.cfl", ph: "auto by regime" },
      { k: "Max CFL", path: "solver.cfl_max", ph: "auto" },
      { k: "Threads (OpenMP builds)", path: "solver.threads", ph: dv.threads + " (all cores)" },
    ]) + actions([updBtn("setup", "Write config"), `<button data-upto="results">⚡ Solve</button>`]) + stepNote("setup") + notesList(dv.notes);
  } else if (n === "solve" || n === "solinfo") {
    title = "Details of \"Solution\"";
    const e = ST.steps.solve;
    h = grid([{ sec: "Run" }, { k: "Solver", ro: `SU2 ${dv.solver}` }, { k: "Threads", ro: dv.threads },
      { k: "Iterations run", ro: e?.info?.iterations_run ?? "—" }, { k: "Wall time", ro: e?.seconds != null ? e.seconds + " s" : "—" }]) +
      actions([`<button class="primary" data-upto="results">⚡ Solve</button>`, `<button data-stop>■ Stop</button>`]) + stepNote("solve") +
      note("Live residuals, lift and the time estimate are in <b>Solution Information</b> (bottom). The SU2 release build runs on one core: 2D RANS ≈ 2–4 it/s, 3D Euler (90 k tets) converges in ~1–2 min.");
  } else if (n === "results" || n === "res3d" || n.startsWith("img:")) {
    title = "Details of \"Results\"";
    const r = ST.steps.results?.info || {}, s = r.summary || {};
    h = grid([{ sec: "Forces (" + (dv.half ? "half model" : "per reference") + ")" },
      { k: "CL", ro: fmt(s.CL) }, { k: "CD", ro: fmt(s.CD) + (dv.dim === 3 && !dv.viscous ? "  (inviscid, coarse — indicative)" : "") },
      { k: "CM (about x_ref)", ro: fmt(s.CMy ?? s.CMz ?? s.CM) }, { k: "L/D", ro: s.CD ? fmt(s.CL / s.CD, 3) : "—" },
      { sec: "Convergence" }, { k: "Converged", ro: s.converged === undefined ? "—" : s.converged ? "Yes" : "NO" },
      { k: "Residual drop", ro: s.residual_drop_orders != null ? fmt(s.residual_drop_orders, 3) + " orders" : "—" },
      ...(s.yplus_mean != null ? [{ k: "Wall y+ mean / max", ro: `${fmt(s.yplus_mean, 3)} / ${fmt(s.yplus_max, 3)}` }] : []),
      ...(r.estimate?.CL != null ? [{ sec: "Hand estimate" }, { k: r.estimate.method, ro: "CL ≈ " + fmt(r.estimate.CL) }] : []),
    ]) + actions([updBtn("results", "Re-post-process")]) + stepNote("results") +
      (r.checks ? `<div class="dnote"><b>Verification checks</b></div>` + checksHtml(r.checks) : "");
  } else if (n === "polar") {
    title = "Details of \"Polar Sweep\"";
    const p = ST.steps.polar?.info || {};
    const k = String(S().conditions.polar || "").split(/[,;]/).filter((x) => x.trim()).length;
    h = grid([{ sec: "Sweep" }, { k: "Angles of attack", path: "conditions.polar", type: "text", unit: "°", ph: "e.g. 0, 2, 4, 6, 8" },
      { k: "Design point (Flow Conditions)", ro: S().conditions.aoa + "°" },
      ...(p.rows ? [{ sec: "Results" }, ...p.rows.map((r) => ({ k: `α = ${r.alpha}°${r.converged ? "" : "  ✖ not converged"}`, ro: `CL ${fmt(r.CL)} · CD ${fmt(r.CD)} · CM ${fmt(r.CM)}` }))] : []),
    ]) + actions([updBtn("polar", "Run sweep"), p.csv ? `<a class="btn" href="${fileURL(p.csv, ST.steps.polar.finished)}&dl=1">polar.csv</a>` : ""]) + stepNote("polar") +
      note(`One SU2 run per angle, each restarted from the nearest converged solution. ${k ? `≈ ${k} × the design-point solve time.` : ""} ${p.note ? esc(p.note) : ""}`);
  } else if (n === "structure" || n === "structural") {
    title = "Details of \"Static Structural\"";
    const t = S().structure;
    h = grid([{ sec: "Model" },
      { k: "Run structure", path: "structure.enabled", type: "select", opts: [["true", "Yes"], ["false", "No"]] },
      { k: "Model", path: "structure.model", type: "select", opts: [["shell", "Shell – thin skin (S6)"], ["solid", "Solid – filled part (C3D10)"]] },
      ...(t.model === "shell" ? [{ k: "Skin thickness", path: "structure.thickness", unit: "m" }] : []),
      { k: "Element size", path: "structure.h", unit: "m", ph: "auto (span/60)" },
      { sec: "Material" },
      { k: "Material", path: "structure.material", type: "select", opts: ST.materials.map((m) => [m, m]) },
      { k: "E override", path: "structure.E", unit: "Pa", ph: "library" }, { k: "ν override", path: "structure.nu", ph: "library" },
      { k: "Allowable override", path: "structure.allowable", unit: "Pa", ph: "library" },
      { sec: "Loads & supports" },
      { k: "Load factor on CFD pressure", path: "structure.load_factor", ph: "1.5 = ultimate" },
      { k: "Clamp axis", path: "structure.clamp_axis", type: "select", opts: [["y", "y (wing root)"], ["x", "x"], ["z", "z"]] },
      { k: "Clamp: fix nodes with coord ≤", path: "structure.clamp_value", unit: "m", ph: "auto (root)" },
    ]) + actions([updBtn("structure", "Solve Structure")]) + stepNote("structure") +
      note("One-way coupling: CFD gauge pressure → consistent nodal forces → CalculiX linear static. No buckling, fatigue or ply failure. Inertia relief not included (conservative).");
  } else if (n === "feasol" || n.startsWith("fea:")) {
    title = "Details of \"Structural Solution\"";
    const f = ST.steps.structure?.info || {}, s = f.summary || {};
    h = grid([{ sec: "Results" },
      { k: "Max von Mises (clamp)", ro: s.max_von_mises_Pa != null ? fmt(s.max_von_mises_Pa / 1e6) + " MPa" : "—" },
      { k: "Max von Mises away from clamp", ro: s.max_von_mises_away_from_clamp_Pa != null ? fmt(s.max_von_mises_away_from_clamp_Pa / 1e6) + " MPa" : "—" },
      { k: "Reserve factor", ro: fmt(s.reserve_factor_away_from_clamp, 3) },
      { k: "Max displacement", ro: s.max_displacement_m != null ? fmt(s.max_displacement_m * 1e3) + " mm" : "—" },
      { k: "Tip deflection (z)", ro: s.tip_deflection_z_m != null ? fmt(s.tip_deflection_z_m * 1e3) + " mm" : "—" },
      { k: "Nodes", ro: s.n_nodes?.toLocaleString() ?? "—" },
      { k: "Applied force", ro: s.applied_force_N ? s.applied_force_N.map((v) => fmt(v, 4)).join(", ") + " N" : "—" },
    ]) + actions([updBtn("structure", "Solve Structure")]) + stepNote("structure") +
      (f.checks ? `<div class="dnote"><b>Checks</b></div>` + checksHtml(f.checks) : "");
  } else if (n === "report") {
    title = "Details of \"Report\"";
    const e = ST.steps.report;
    h = actions([updBtn("report", "Generate report"),
      e?.status === "ok" ? `<a class="btn" target="_blank" href="${fileURL("report/report.html", e.finished)}">Open HTML</a>
        <a class="btn" href="${fileURL("report/report.md", e.finished)}&dl=1">report.md</a>` : ""]) + stepNote("report") +
      note("Summary, geometry & references, flow conditions, mesh, solver setup, convergence & checks, aerodynamic and structural results, limitations.");
  } else if (n === "handoff") {
    title = "Details of \"Handoff Package\"";
    const e = ST.steps.handoff;
    h = actions([updBtn("handoff", "Build package"),
      e?.status === "ok" ? `<a class="btn" href="${fileURL(e.info.zip, e.finished)}&dl=1">⬇ Download (${e.info.size_mb} MB)</a>` : ""]) + stepNote("handoff") +
      note("Mesh, SU2 config, CalculiX input, results, report, the pipeline scripts and <code>run_all.sh</code> with every command used — refine on a workstation or cluster.");
  }
  $("#detailsTitle").textContent = title;
  box.innerHTML = h;
  // wire inputs
  $$("#details [data-path]").forEach((el) => { if (DEMO) el.disabled = true; el.addEventListener("change", () => saveField(el)); });
  $$("#details input[data-path]").forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.blur(); }));
  $$("#details [data-upto]").forEach((b) => b.onclick = () => runSteps(b.dataset.upto));
  $$("#details [data-import]").forEach((b) => b.onclick = () => $("#fileInput").click());
  $$("#details [data-stop]").forEach((b) => b.onclick = () => post(`/api/case/${cid}/stop`));
}

async function saveField(el) {
  const path = el.dataset.path.split(".");
  let v = el.value.trim();
  if (el.dataset.type === "num") {
    if (v === "") v = null;
    else { v = Number(v.replace(",", ".")); if (!Number.isFinite(v)) { el.style.color = "var(--err)"; return; } }
  }
  if (v === "true") v = true; if (v === "false") v = false;
  const body = path.length === 1 ? { [path[0]]: v } : { [path[0]]: { [path[1]]: v } };
  try {
    await post(`/api/case/${cid}/settings`, body);
    await refresh(true);
    if (path[1] === "source" && (v === "cad" || v === "dat2d") && !get("geometry.cad_file")) $("#fileInput").click();
  } catch (e) { notify(e.message, true); }
}

// --------------------------------------------------------------------------- 3D viewer
const V = { inited: false };
function initViewer() {
  const canvas = $("#three");
  V.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  V.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  V.scene = new THREE.Scene();
  V.camera = new THREE.PerspectiveCamera(35, 1, 0.001, 1e5);
  V.camera.up.set(0, 0, 1);
  V.controls = new OrbitControls(V.camera, canvas);
  V.controls.enableDamping = true; V.controls.dampingFactor = 0.15;
  V.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const dl = new THREE.DirectionalLight(0xffffff, 1.6); dl.position.set(-1, -2, 3); V.camera.add(dl); V.scene.add(V.camera);
  V.group = new THREE.Group(); V.scene.add(V.group);
  V.edges = true;
  const ro = new ResizeObserver(resize); ro.observe($("#viewport"));
  V.inited = true;
  (function loop() { requestAnimationFrame(loop); V.controls.update(); V.renderer.render(V.scene, V.camera); drawTriad(); })();
}
function resize() {
  const el = $("#viewport"), w = el.clientWidth, h = el.clientHeight;
  if (!w || !h) return;
  V.renderer.setSize(w, h, false); V.camera.aspect = w / h; V.camera.updateProjectionMatrix();
}
const BANDS = ["#0000ff", "#0059ff", "#00b3ff", "#00ffe5", "#00ff6a", "#4dff00", "#c4ff00", "#ffd000", "#ff6a00", "#ff0000"];
function bandTexture() {
  const n = BANDS.length, data = new Uint8Array(n * 4);
  BANDS.forEach((c, i) => { const col = new THREE.Color(c); data.set([col.r * 255, col.g * 255, col.b * 255, 255], i * 4); });
  const t = new THREE.DataTexture(data, n, 1); t.magFilter = t.minFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
  t.needsUpdate = true; return t;
}
const cache = new Map();
async function loadJSON(url) { if (!cache.has(url)) cache.set(url, fetch(url).then((r) => { if (!r.ok) throw new Error("load failed"); return r.json(); })); return cache.get(url); }

function clearGroup() { while (V.group.children.length) { const o = V.group.children.pop(); o.geometry?.dispose(); o.material?.dispose(); } }

async function show3D(url, opts = {}) {
  if (!V.inited) initViewer();
  setView("three");
  $("#vpEmpty").textContent = "Loading…";
  let d;
  try { d = await loadJSON(url); } catch (e) { $("#vpEmpty").textContent = "Could not load " + url; return; }
  $("#vpEmpty").textContent = "";
  V.data = d; V.opts = opts;
  const fields = Object.keys(d.fields || {});
  V.field = opts.field && fields.includes(opts.field) ? opts.field : fields[0] || null;
  V.dscale = opts.deform ? (d.disp_scale || 1) : 0;
  buildMesh(true);
  // controls
  const c = $("#vpCtrl");
  if (fields.length || d.disp) {
    c.hidden = false;
    c.innerHTML = (fields.length ? `<label>Result <select id="fSel">${fields.map((f) => `<option${f === V.field ? " selected" : ""}>${esc(f)}</option>`).join("")}</select></label>` : "") +
      (d.disp ? `<label>Deformation <select id="dSel">
        ${[["0", "Undeformed"], ["1", "True scale"], [String(d.disp_scale || 1), `Auto (${d.disp_scale}×)`], [String((d.disp_scale || 1) * 3), `${(d.disp_scale || 1) * 3}×`]]
          .map(([v, l]) => `<option value="${v}"${+v === V.dscale ? " selected" : ""}>${l}</option>`).join("")}</select></label>` : "");
    $("#fSel") && ($("#fSel").onchange = (e) => { V.field = e.target.value; buildMesh(false); });
    $("#dSel") && ($("#dSel").onchange = (e) => { V.dscale = +e.target.value; buildMesh(false); });
  } else c.hidden = true;
}
function buildMesh(fit) {
  clearGroup();
  const d = V.data, n = d.xyz.length;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const p = d.xyz[i], u = d.disp && V.dscale ? d.disp[i] : null;
    pos[3 * i] = p[0] + (u ? u[0] * V.dscale : 0); pos[3 * i + 1] = p[1] + (u ? u[1] * V.dscale : 0); pos[3 * i + 2] = p[2] + (u ? u[2] * V.dscale : 0);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setIndex(d.tris.flat());
  geo.computeVertexNormals();
  let mat;
  const vals = V.field ? d.fields[V.field] : null;
  if (vals) {
    let lo = Infinity, hi = -Infinity;
    for (const v of vals) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const uv = new Float32Array(n * 2), span = hi - lo || 1;
    for (let i = 0; i < n; i++) { uv[2 * i] = Math.min(0.9999, Math.max(0.0001, (vals[i] - lo) / span)); uv[2 * i + 1] = 0.5; }
    geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    mat = new THREE.MeshLambertMaterial({ map: bandTexture(), side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    legend(V.field, lo, hi);
  } else {
    mat = new THREE.MeshLambertMaterial({ color: 0xb9c4cf, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    $("#legend").hidden = true;
  }
  const mesh = new THREE.Mesh(geo, mat); V.group.add(mesh);
  const showEdges = V.opts.wire;
  if (showEdges || ($("#bEdges").classList.contains("on"))) {
    const w = new THREE.LineSegments(new THREE.WireframeGeometry(geo), new THREE.LineBasicMaterial({ color: 0x1a2a3a, transparent: true, opacity: V.opts.wire ? 0.55 : 0.3 }));
    V.group.add(w);
  }
  // undeformed outline for deformation plots
  if (d.disp && V.dscale) {
    const g0 = new THREE.BufferGeometry(); g0.setAttribute("position", new THREE.BufferAttribute(new Float32Array(d.xyz.flat()), 3)); g0.setIndex(d.tris.flat());
    V.group.add(new THREE.LineSegments(new THREE.EdgesGeometry(g0, 30), new THREE.LineBasicMaterial({ color: 0x333333, transparent: true, opacity: 0.35 })));
  }
  geo.computeBoundingSphere(); V.bs = geo.boundingSphere;
  $("#vpInfo").innerHTML = `${n.toLocaleString()} nodes · ${d.tris.length.toLocaleString()} faces` + (V.dscale ? `<br>Deformation scale ${V.dscale}×` : "");
  if (fit) view(V.lastView || "iso");
}
function legend(name, lo, hi) {
  const L = $("#legend"); L.hidden = false;
  const n = BANDS.length;
  let rows = "";
  for (let i = n; i >= 0; i--) {
    const v = lo + (hi - lo) * i / n;
    rows += `<div class="row"><span class="sw" style="background:${i === n ? "transparent;border:0" : BANDS[i]}"></span><span class="${i === n || i === 0 ? "mx" : ""}">${fmt(v, 4)}${i === n ? " Max" : i === 0 ? " Min" : ""}</span></div>`;
  }
  L.innerHTML = `<div class="lt">${esc(name)}</div>${rows}`;
}
function view(kind) {
  if (!V.bs) return;
  V.lastView = kind === "fit" ? (V.lastView || "iso") : kind;
  const k = kind === "fit" ? V.lastView : kind;
  const c = V.bs.center, r = V.bs.radius;
  const dirs = { iso: [-1.0, -1.25, 0.95], top: [0, 0, 1], front: [-1, 0, 0], side: [0, -1, 0] };
  const dir = new THREE.Vector3(...dirs[k]).normalize();
  const dist = r / Math.sin(THREE.MathUtils.degToRad(V.camera.fov / 2)) * 1.05;
  V.camera.position.copy(c).addScaledVector(dir, dist);
  V.camera.up.set(0, 0, 1);
  if (k === "top") V.camera.up.set(0, 1, 0);
  V.camera.near = dist / 200; V.camera.far = dist * 50; V.camera.updateProjectionMatrix();
  V.controls.target.copy(c); V.camera.lookAt(c); V.controls.update();
}
function drawTriad() {
  const el = $("#triad"); if ($("#three").style.display === "none") { el.innerHTML = ""; return; }
  const m = V.camera.matrixWorldInverse;
  const ax = [["X", 0xd32f2f, [1, 0, 0]], ["Y", 0x2e7d32, [0, 1, 0]], ["Z", 0x1565c0, [0, 0, 1]]];
  let s = `<svg viewBox="-35 -35 70 70" width="70" height="70">`;
  for (const [l, c, v] of ax) {
    const p = new THREE.Vector3(...v).transformDirection(m);
    const x = p.x * 24, y = -p.y * 24, col = "#" + c.toString(16).padStart(6, "0");
    s += `<line x1="0" y1="0" x2="${x}" y2="${y}" stroke="${col}" stroke-width="2.5"/><text x="${x * 1.25}" y="${y * 1.25 + 4}" font-size="11" font-weight="700" fill="${col}" text-anchor="middle">${l}</text>`;
  }
  el.innerHTML = s + "</svg>";
}

function setView(kind) {
  $("#three").style.display = kind === "three" ? "block" : "none";
  $("#imgView").hidden = kind !== "img";
  $("#svgView").hidden = kind !== "svg";
  if (kind !== "three") { $("#legend").hidden = true; $("#vpCtrl").hidden = true; $("#vpInfo").textContent = ""; }
  $("#vpEmpty").textContent = "";
}
function showImg(rel, bust) {
  setView("img");
  $("#imgEl").src = fileURL(rel, bust);
  $("#imgEl").alt = resName(rel);
}
function showEmpty(msg) { setView("none"); $("#vpEmpty").innerHTML = `<div>${msg}</div>`; }

function airfoilSVG(pts, title) {
  setView("svg");
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), c = x1 - x0, y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = 0.08 * c, W = c + 2 * pad, H = Math.max((y1 - y0) + 2 * pad, 0.45 * c);
  const cy = (y0 + y1) / 2;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${(p[0] - x0 + pad).toFixed(5)},${(cy - p[1] + H / 2).toFixed(5)}`).join("") + "Z";
  const sw = c / 600;
  $("#svgView").innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    <line x1="${pad}" y1="${H / 2 + cy}" x2="${pad + c}" y2="${H / 2 + cy}" stroke="#8796a6" stroke-dasharray="${c / 100}" stroke-width="${sw}"/>
    <path d="${path}" fill="#b9c4cf" stroke="#1d2b39" stroke-width="${sw * 1.5}"/>
    <text x="${pad}" y="${pad * 0.7}" font-size="${c / 32}" fill="#22303d">${esc(title)}</text></svg>`;
}

// --------------------------------------------------------------------------- graphics per selection
let shown = "";
function graphics(force) {
  if (!ST) { showEmpty("Create a project with <b>New</b>, or pick one from the list."); return; }
  const n = sel, dv = ST.derived, steps = ST.steps;
  const sig = n + "|" + JSON.stringify([steps.geometry?.finished, steps.mesh?.finished, steps.results?.finished, steps.structure?.finished]);
  if (!force && sig === shown) return;
  shown = sig;
  $("#gTitle").textContent = "Graphics";
  const geo = steps.geometry?.info, ok = (s) => steps[s]?.status === "ok" || steps[s]?.status === "stale";
  const geomView = () => {
    if (!ok("geometry")) return showEmpty("Geometry not generated yet.<br>Set it up in <b>Details</b>, then press <b>⚡ Update</b> (or Generate Mesh).");
    if (dv.dim === 2 && geo?.airfoil) return airfoilSVG(geo.airfoil, `Airfoil, chord ${S().geometry.chord} m`);
    if (geo?.viewer) return show3D(fileURL(geo.viewer, steps.geometry.finished), {});
    showEmpty("No preview.");
  };
  if (["geometry", "project", "model", "conditions", "references"].includes(n)) return geomView();
  if (n === "mesh") {
    if (!ok("mesh")) return showEmpty("No mesh yet — press <b>Generate Mesh</b>.");
    const mi = steps.mesh.info;
    if (mi.viewer) return show3D(fileURL(mi.viewer, steps.mesh.finished), { wire: true });
    return showImg(mi.image, steps.mesh.finished);
  }
  if (["setup", "fluid", "solve", "solinfo"].includes(n)) {
    if (ok("results")) { const r = steps.results.info; return r.viewer ? show3D(fileURL(r.viewer, steps.results.finished), { field: "Cp" }) : showImg(r.images.find((x) => /contour_mach\.png/.test(x)) || r.images[0], steps.results.finished); }
    if (n === "solinfo" || n === "solve") {
      if (!ok("mesh")) return showEmpty("Mesh and solve first.");
      const mi = steps.mesh.info;
      return mi.viewer ? show3D(fileURL(mi.viewer, steps.mesh.finished), { wire: true }) : showImg(mi.image, steps.mesh.finished);
    }
    return geomView();
  }
  if (n === "results" || n === "res3d") {
    if (!ok("results")) return showEmpty("No results yet — press <b>⚡ Solve</b>.");
    const r = steps.results.info;
    if (r.viewer) return show3D(fileURL(r.viewer, steps.results.finished), { field: "Cp" });
    return showImg(r.images.find((x) => /contour_mach\.png/.test(x)) || r.images[0], steps.results.finished);
  }
  if (n === "polar") return ok("polar") && steps.polar.info?.images ? showImg(steps.polar.info.images[0], steps.polar.finished) : showEmpty("List angles under <b>Details</b> and press <b>Run sweep</b>.");
  if (n.startsWith("img:")) return showImg(n.slice(4), steps.results?.finished || steps.structure?.finished);
  if (n.startsWith("fea:") || n === "feasol" || n === "structure" || n === "structural") {
    const f = steps.structure?.info;
    if (!ok("structure") || !f?.viewer) return n.startsWith("fea") || n === "feasol" ? showEmpty("Run <b>Structural</b> first.") : geomView();
    const field = n.startsWith("fea:") ? n.slice(4) : "von Mises [MPa]";
    return show3D(fileURL(f.viewer, steps.structure.finished), { field, deform: field.startsWith("|u|") || n === "feasol" });
  }
  if (n === "report") {
    if (steps.report?.status === "ok" && DEMO) {
      setView("none");
      const host = document.createElement("div");
      host.style.cssText = "position:absolute;inset:0;overflow:auto;background:#fff;pointer-events:auto;text-align:left;max-width:none";
      $("#vpEmpty").innerHTML = ""; $("#vpEmpty").appendChild(host);
      fetch(fileURL("report/report.html")).then((r) => r.text()).then((t) => {
        const root = host.attachShadow({ mode: "open" });
        const b = t.match(/<body>([\s\S]*)<\/body>/), st = t.match(/<style>([\s\S]*?)<\/style>/);
        root.innerHTML = `<style>${st ? st[1].replace(/body\{/, ".rep{") : ""}</style><div class="rep">${b ? b[1] : t}</div>`;
      });
      return;
    }
    if (steps.report?.status === "ok") { setView("none");
      $("#vpEmpty").innerHTML = `<iframe src="${fileURL("report/report.html", steps.report.finished)}" style="position:absolute;inset:0;width:100%;height:100%;border:0;background:#fff;pointer-events:auto"></iframe>`; return; }
    return showEmpty("Report not generated yet.");
  }
  if (n === "handoff") return showEmpty(steps.handoff?.status === "ok" ? "Package ready — download it from <b>Details</b>." : "Build the package from <b>Details</b>.");
  geomView();
}

// --------------------------------------------------------------------------- bottom: log, chart, worksheet
function colorLog(t) {
  return esc(t.replace(/\x1b\[[0-9;]*m/g, "")).split("\n").map((l) =>
    l.startsWith("$ ") ? `<span class="cmd">${l}</span>` : l.startsWith("=====") ? `<span class="hdr">${l}</span>` :
    /^\*\*\*|Error|error:|failed/.test(l) ? `<span class="err">${l}</span>` : l).join("\n");
}
async function pollLog() {
  if (!cid) return;
  const r = await api(`/api/case/${cid}/log?from=${logPos}`).catch(() => null);
  if (!r) return;
  const el = $("#tab-messages");
  if (r.next < logPos) el.innerHTML = "";
  if (r.text) {
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.insertAdjacentHTML("beforeend", colorLog(r.text));
    if (el.childNodes.length > 4000) el.innerHTML = el.innerHTML.slice(-300000);
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
  logPos = r.next;
}
async function drawChart() {
  if (!cid) return;
  const h = await api(`/api/case/${cid}/history`).catch(() => null);
  const cv = $("#resChart"), box = cv.parentElement;
  const W = box.clientWidth, H = box.clientHeight; if (!W || !H) return;
  const dpr = devicePixelRatio || 1; cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, W, H); g.font = "11px Segoe UI, sans-serif";
  if (!h || !h.data || !h.data.Inner_Iter) { g.fillStyle = "#5d6874"; g.fillText("No solver history yet.", 12, 20); return; }
  const it = h.data.Inner_Iter, res = h.columns.filter((c) => c.startsWith("rms["));
  const half = W > 640 ? W / 2 : W;
  const panel = (x0, w, series, title, logy) => {
    const L = x0 + 46, R = x0 + w - 12, T = 18, B = H - 22;
    let lo = Infinity, hi = -Infinity;
    series.forEach(([, d]) => d.forEach((v) => { if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    if (!(hi > lo)) { hi = lo + 1; lo -= 1; }
    const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    const xmax = Math.max(it[it.length - 1], 1), X = (v) => L + (R - L) * v / xmax, Y = (v) => B - (B - T) * (v - lo) / (hi - lo);
    g.strokeStyle = "#dde1e6"; g.lineWidth = 1; g.fillStyle = "#5d6874";
    for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4, y = Y(v); g.beginPath(); g.moveTo(L, y); g.lineTo(R, y); g.stroke(); g.fillText(logy ? v.toFixed(1) : (+v.toPrecision(3)).toString(), x0 + 4, y + 4); }
    g.fillText("0", L - 3, B + 14); g.fillText(String(Math.round(xmax)), R - 24, B + 14);
    g.strokeStyle = "#9aa4ae"; g.strokeRect(L, T, R - L, B - T);
    g.fillStyle = "#1c2530"; g.font = "600 11.5px Segoe UI, sans-serif"; g.fillText(title, L, 12); g.font = "11px Segoe UI, sans-serif";
    const cols = ["#d32f2f", "#1565c0", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f", "#5d4037"];
    let lx = R - 4;
    series.forEach(([name, d], k) => {
      g.strokeStyle = cols[k % cols.length]; g.lineWidth = 1.3; g.beginPath();
      d.forEach((v, i) => { const x = X(it[i]), y = Y(v); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
      const tw = g.measureText(name).width; lx -= tw + 22;
      g.fillStyle = cols[k % cols.length]; g.fillRect(lx, T + 6, 12, 3); g.fillStyle = "#1c2530"; g.fillText(name, lx + 15, T + 11);
    });
  };
  panel(0, half, res.map((c) => [c.replace("rms[", "").replace("]", ""), h.data[c]]), "log₁₀ RMS residuals", true);
  const last = (k) => h.data[k] ? h.data[k][h.data[k].length - 1] : null;
  const nowIt = it[it.length - 1], now = Date.now();
  if (!RATE.t || RATE.cid !== cid || nowIt < RATE.it) Object.assign(RATE, { cid, t: now, it: nowIt, r: null });
  else if (now - RATE.t > 4000 && nowIt > RATE.it) { const r = (nowIt - RATE.it) / ((now - RATE.t) / 1000); RATE.r = RATE.r ? 0.6 * RATE.r + 0.4 * r : r; RATE.t = now; RATE.it = nowIt; }
  const maxIt = ST?.derived?.iterations;
  const solving = ST?.steps?.solve?.status === "running";
  if (solving && RATE.r && maxIt) $("#statusText").textContent = `◌ Solving: iter ${nowIt} / ${maxIt} · ${RATE.r.toFixed(1)} it/s · ≤ ${Math.ceil((maxIt - nowIt) / RATE.r / 60)} min left (stops early at the residual target)`;
  if (W > 640) panel(half, half, [["CL", h.data.CL || []]], `Lift coefficient   CL = ${fmt(last("CL"))}   CD = ${fmt(last("CD"))}   (iter ${it[it.length - 1]})`, false);
}
async function worksheet() {
  const el = $("#tab-worksheet");
  if (!ST) { el.innerHTML = ""; return; }
  const n = sel, st = ST.steps;
  if ((n === "setup" || n === "fluid") && st.setup?.info?.cfg) { el.innerHTML = `<b>run/case.cfg</b><pre>${esc(st.setup.info.cfg)}</pre>`; return; }
  const tbl = (o) => `<table>${Object.entries(o).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" ? JSON.stringify(v) : (typeof v === "number" ? fmt(v, 6) : v))}</td></tr>`).join("")}</table>`;
  if (n === "conditions" && st.conditions?.info?.cond) { el.innerHTML = `<b>cond.json</b>` + tbl(st.conditions.info.cond); return; }
  if ((n === "results" || n === "res3d" || n.startsWith("img:")) && st.results?.info?.summary) { el.innerHTML = `<b>run/results/summary.json</b>` + tbl(st.results.info.summary); return; }
  if ((n.startsWith("fea") || n === "structure" || n === "structural") && st.structure?.info?.summary) { el.innerHTML = `<b>fea/fea_summary.json</b>` + tbl(st.structure.info.summary); return; }
  if (n === "polar" && st.polar?.info?.rows) { el.innerHTML = `<b>run/polar/polar.csv</b><table><tr><th>α [°]</th><th>CL</th><th>CD</th><th>CM</th><th>converged</th><th>restart from</th></tr>${st.polar.info.rows.map((r) => `<tr><td>${r.alpha}</td><td>${fmt(r.CL)}</td><td>${fmt(r.CD)}</td><td>${fmt(r.CM)}</td><td>${r.converged ? "yes" : "NO"}</td><td>${r.restart_from ?? "—"}</td></tr>`).join("")}</table>`; return; }
  if (n === "mesh" && st.mesh?.info) { el.innerHTML = `<b>Mesh statistics</b>` + tbl(st.mesh.info); return; }
  const t = await fetch(fileURL("commands.sh", Date.now())).then((r) => r.text()).catch(() => "");
  el.innerHTML = `<b>commands.sh</b> – every command run for this case (reproducible outside the app)<pre>${esc(t)}</pre>`;
}
function setTab(t) {
  $$("#bTabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  ["messages", "solinfo", "worksheet"].forEach((k) => $("#tab-" + k).hidden = k !== t);
  if (t === "solinfo") drawChart();
  if (t === "worksheet") worksheet();
}
const curTab = () => $("#bTabs .on")?.dataset.tab;

// --------------------------------------------------------------------------- actions
async function runSteps(upto) {
  try {
    await post(`/api/case/${cid}/run`, upto ? { upto } : {});
    await refresh(true);
    schedule(600);
  } catch (e) { notify(e.message, true); }
}
function select(id) {
  sel = id;
  buildTree(); details(); graphics(true);
  if (curTab() === "worksheet") worksheet();
  if (id === "solinfo") setTab("solinfo");
}

async function refresh(full) {
  if (!cid) return;
  const prevRunning = ST?.running;
  try { ST = await api(`/api/case/${cid}/state`); } catch (e) { return; }
  $("#caseTitle").textContent = ST.settings.name;
  const sig = JSON.stringify([ST.steps, ST.queued, ST.settings]);
  if (full || sig !== lastSig) {
    lastSig = sig;
    buildTree();
    if (!document.activeElement?.closest?.("#details")) details();
    graphics(false);
  }
  const running = Object.entries(ST.steps).find(([, v]) => v.status === "running");
  if (!(running && running[0] === "solve" && RATE.r)) $("#statusText").textContent = running ? `◌ Running: ${ST.labels[running[0]]}…  ${ST.queued.length ? "(then " + ST.queued.map((q) => ST.labels[q]).join(", ") + ")" : ""}`
    : prevRunning && !ST.running ? "Done." : "";
  $("#bStop").disabled = !ST.running;
  if (running && running[0] === "solve" && curTab() === "messages" && !V.userTab) setTab("solinfo");
  if (curTab() === "solinfo" && (running || prevRunning)) drawChart();
}
function schedule(ms) { clearTimeout(pollT); pollT = setTimeout(tick, ms); }
async function tick() { if (DEMO) return; await refresh(false); await pollLog(); schedule(ST?.running ? 1500 : 5000); }

async function loadCases(selectId) {
  const list = await api("/api/cases");
  $("#caseSelect").innerHTML = list.length ? list.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} · ${c.dim || "?"}D · ${esc(c.created || "")}</option>`).join("")
    : `<option value="">(no projects)</option>`;
  const has = (x) => x && list.some((c) => c.id === x);
  const id = has(selectId) ? selectId : has(cid) ? cid : list[0]?.id;
  if (id) { $("#caseSelect").value = id; await openCase(id); }
  else { cid = null; ST = null; buildTree(); details(); graphics(true); newDialog(); }
}
async function openCase(id) {
  cid = id; logPos = 0; lastSig = ""; shown = ""; sel = "geometry";
  localStorageSafe("set", "aerosim.case", id);
  $("#tab-messages").innerHTML = "";
  await refresh(true); await pollLog(); details(); graphics(true);
  if (curTab() === "solinfo") drawChart();
}
function localStorageSafe(op, k, v) { try { return op === "set" ? localStorage.setItem(k, v) : localStorage.getItem(k); } catch { return null; } }

function newDialog() { $("#newModal").hidden = false; $("#newName").focus(); $("#newName").select(); }
$("#bNew").onclick = () => DEMO ? notify(DEMO_MSG, true) : newDialog();
$("#newCancel").onclick = () => $("#newModal").hidden = true;
$("#newOk").onclick = async () => {
  const tpl = $$("input[name=tpl]").find((r) => r.checked).value;
  const r = await post("/api/cases", { name: $("#newName").value || "New case", template: tpl === "airfoil" ? "airfoil" : null });
  $("#newModal").hidden = true;
  await loadCases(r.id);
  if (tpl === "cad") { await post(`/api/case/${cid}/settings`, { geometry: { source: "cad" } }); await refresh(true); $("#fileInput").click(); }
};
$("#caseSelect").onchange = (e) => e.target.value && openCase(e.target.value);
$("#bDelete").onclick = async () => {
  if (!cid) return;
  if (DEMO) return notify(DEMO_MSG, true);
  if (!confirm(`Delete project "${ST?.settings?.name}" and all its files?`)) return;
  try { await post(`/api/case/${cid}/delete`); cid = null; await loadCases(); } catch (e) { notify(e.message, true); }
};
$("#bImport").onclick = () => DEMO ? notify(DEMO_MSG, true) : cid ? $("#fileInput").click() : newDialog();
$("#fileInput").onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = ""; if (!f || !cid) return;
  $("#statusText").textContent = `Uploading ${f.name}…`;
  try {
    await api(`/api/case/${cid}/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f });
    sel = "geometry"; await refresh(true); await runSteps("geometry");
  } catch (err) { notify(err.message, true); }
};
$$("[data-run]").forEach((b) => b.onclick = () => cid && runSteps(b.dataset.run));
$("#bStop").onclick = () => cid && post(`/api/case/${cid}/stop`);
$$("[data-open]").forEach((b) => b.onclick = () => {
  if (!cid) return;
  const k = b.dataset.open, e = ST.steps[k];
  if (e?.status === "ok") {
    if (k === "report") select("report");
    else if (DEMO) notify("The handoff zip is produced by the installed app (Package button).", true);
    else location.href = fileURL(e.info.zip, e.finished) + "&dl=1";
  } else runSteps(k);
});
$$("[data-view]").forEach((b) => b.onclick = () => { if ($("#three").style.display !== "none") view(b.dataset.view); });
$("#bEdges").onclick = () => { $("#bEdges").classList.toggle("on"); if (V.data && $("#three").style.display !== "none") buildMesh(false); };
$$("#bTabs [data-tab]").forEach((b) => b.onclick = () => { V.userTab = true; setTab(b.dataset.tab); });
window.addEventListener("resize", () => curTab() === "solinfo" && drawChart());

// splitters
(function splitters() {
  const left = $(".left");
  $(".vsplit").onmousedown = (e) => {
    const x0 = e.clientX, w0 = left.offsetWidth;
    const mv = (ev) => left.style.width = Math.max(220, Math.min(700, w0 + ev.clientX - x0)) + "px";
    const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up);
  };
  $$(".hsplit").forEach((s) => s.onmousedown = (e) => {
    const target = s.dataset.split === "bottom" ? $(".bottom") : $(".outline");
    const y0 = e.clientY, h0 = target.offsetHeight, sign = s.dataset.split === "bottom" ? -1 : 1;
    const mv = (ev) => { target.style.flex = `0 0 ${Math.max(80, h0 + sign * (ev.clientY - y0))}px`; };
    const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); if (curTab() === "solinfo") drawChart(); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up);
  });
})();

// boot
loadCases(localStorageSafe("get", "aerosim.case")).then(() => schedule(1500));
