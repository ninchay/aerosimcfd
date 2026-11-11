"""Write report/report.md (skill §8 structure) and a self-contained report.html."""
import base64, html, json, os, re, shutil


def _f(v, fmt="{:.4g}"):
    try:
        return fmt.format(v)
    except Exception:
        return "—"


def write(d, c, dv, st):
    S = st["steps"]
    out = os.path.join(d, "report")
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    res = (S.get("results") or {}).get("info") or {}
    s = res.get("summary") or {}
    fea = (S.get("structure") or {}).get("info") or {}
    fs = fea.get("summary") or {}
    mesh = (S.get("mesh") or {}).get("info") or {}
    cond = json.load(open(os.path.join(d, "cond.json"))) if os.path.exists(os.path.join(d, "cond.json")) else {}
    est = res.get("estimate") or {}

    def img(rel, cap):
        p = os.path.join(d, rel)
        if not os.path.exists(p):
            return ""
        dst = os.path.join(out, "img", os.path.basename(rel))
        shutil.copy2(p, dst)
        return f"![{cap}](img/{os.path.basename(rel)})\n\n*{cap}*\n"

    g = c["geometry"]; fc = c["conditions"]
    L = []
    w = L.append
    w(f"# {c['name']}\n")
    # ---------------------------------------------------- summary
    w("## Summary\n")
    if s:
        w(f"- **CL = {_f(s.get('CL'))}, CD = {_f(s.get('CD'))}, CM = {_f(s.get('CMy', s.get('CMz', s.get('CM'))))}, "
          f"L/D = {_f(s.get('L/D', (s.get('CL') or 0) / s['CD'] if s.get('CD') else None), '{:.1f}')}** "
          f"at M = {_f(dv.get('mach'), '{:.3f}')}, α = {fc['aoa']}°, altitude {fc['alt']} m "
          f"({dv['solver']}{' ' + dv['turb'] if dv['viscous'] else ''}).")
        w(f"- Convergence: {'converged' if s.get('converged') else '**NOT converged** — numbers are indicative only'}; "
          f"{s.get('convergence_note', '')}.")
    if est.get("CL") is not None and s.get("CL") is not None:
        w(f"- Hand check ({est['method']}): CL ≈ {_f(est['CL'])} vs CFD {_f(s['CL'])}.")
    if fs:
        w(f"- Structure ({fs.get('model')}, {fs.get('material')}, n = {fs.get('load_factor')}): "
          f"max von Mises away from clamp {_f(fs.get('max_von_mises_away_from_clamp_Pa', 0) / 1e6, '{:.1f}')} MPa, "
          f"RF = {_f(fs.get('reserve_factor_away_from_clamp'), '{:.2f}')}, max deflection "
          f"{_f(fs.get('max_displacement_m', 0) * 1e3, '{:.2f}')} mm.")
    if dv["dim"] == 3 and not dv["viscous"]:
        w("- **Main caveat:** inviscid 3D tetrahedral solution — pressure, lift, moments and loads are usable; "
          "drag is not (numerical dissipation on a coarse mesh). Quote CD only after a mesh study.")
    elif dv["dim"] == 3:
        w("- **Main caveat:** 3D RANS with wall functions on tetrahedra; the thick near-wall cells can de-camber the "
          "wing and lower lift — check y+ and compare with the Euler/lifting-line value.")
    else:
        w("- **Main caveat:** fully turbulent RANS (no transition); drag converges slowest with mesh — use the fine "
          "level for drag numbers. Steady RANS past stall is unreliable.")
    w("")
    # ---------------------------------------------------- geometry
    w("## Geometry & references\n")
    src = {"naca2d": f"NACA {g['naca']} airfoil, chord {g['chord']} m (2D)",
           "dat2d": f"Airfoil from {os.path.basename(g.get('cad_file', ''))}, chord {g['chord']} m (2D)",
           "naca_wing": f"Parametric half-wing: NACA {g['naca']}, root chord {g['chord']} m, taper {g['taper']}, "
                        f"semispan {g['semispan']} m, LE sweep {g['sweep']}°, dihedral {g['dihedral']}°, twist {g['twist']}°",
           "cad": f"CAD file {os.path.basename(g.get('cad_file', ''))} (scale {dv.get('scale')} → m, "
                  f"{'half model, symmetry y = 0' if dv.get('half') else 'full body'})"}[dv["source"]]
    w(f"- {src}")
    w(f"- Reference length c_ref = {_f(dv['lref'])} m, area S_ref = {_f(dv['sref'])} m², moment point x = {_f(dv['xmom'])} m")
    for n in dv.get("notes", []):
        w(f"- {n}")
    w("")
    if dv["dim"] == 3 and os.path.exists(os.path.join(d, "geom", "geometry.json")):
        pass
    # ---------------------------------------------------- conditions
    w("## Flow conditions\n")
    if cond:
        w("| Quantity | Value |\n|---|---|")
        for k, lab, fmt in (("altitude_m", "Altitude [m]", "{:.0f}"), ("mach", "Mach", "{:.4f}"),
                            ("speed_mps", "Speed [m/s]", "{:.2f}"), ("T_K", "Temperature [K]", "{:.2f}"),
                            ("p_Pa", "Pressure [Pa]", "{:.1f}"), ("rho", "Density [kg/m³]", "{:.4f}"),
                            ("mu", "Viscosity [Pa·s]", "{:.4e}"), ("q_Pa", "Dynamic pressure [Pa]", "{:.1f}"),
                            ("reynolds", "Reynolds (c_ref)", "{:.3e}"), ("regime", "Regime", "{}")):
            w(f"| {lab} | {_f(cond.get(k), fmt)} |")
        w(f"| Angle of attack [°] | {fc['aoa']} |")
        if dv["dim"] == 3:
            w(f"| Sideslip [°] | {fc.get('beta', 0)} |")
        w("")
    # ---------------------------------------------------- mesh
    w("## Mesh\n")
    if mesh:
        cells = ", ".join(f"{v:,} {k}" for k, v in (mesh.get("cells") or {}).items())
        w(f"- {'2D hybrid: quad boundary layer + triangles' if dv['dim'] == 2 else '3D unstructured tetrahedra'}, "
          f"level *{dv['level']}*: {mesh.get('n_cells', 0):,} cells ({cells}), {mesh.get('n_points', 0):,} points.")
        if s.get("yplus_mean") is not None:
            w(f"- Wall y+: mean {_f(s['yplus_mean'])}, max {_f(s.get('yplus_max'))}.")
        w("")
        w(img("mesh/mesh.png", "Mesh") if dv["dim"] == 2 else img("run/results/mesh.png", "Mesh"))
    # ---------------------------------------------------- solver
    w("## Solver setup\n")
    w(f"- SU2 {dv['solver']}" + (f", {dv['turb']} turbulence model" if dv["viscous"] else "") +
      (", standard wall functions" if dv["wall_functions"] else "") + f", {dv['iterations']} iterations max.")
    w("- Roe + MUSCL; Venkatakrishnan limiter at M ≥ 0.75; adaptive CFL (regime-based defaults from write_su2_config.py).")
    w("- BCs: wall (no-slip RANS / slip Euler), far-field" + (", symmetry at y = 0" if dv.get("half") else "") + ".\n")
    # ---------------------------------------------------- checks
    w("## Convergence & checks\n")
    for ch in (res.get("checks") or []) + (fea.get("checks") or []):
        mark = "✅" if ch["ok"] else ("⚠️" if ch["ok"] is None else "❌")
        w(f"- {mark} **{ch['name']}** — {ch['detail']}")
    w("")
    w(img("run/results/convergence.png", "Residuals and force history"))
    # ---------------------------------------------------- aero
    w("## Aerodynamic results\n")
    if s:
        w("| CL | CD | CM | L/D |\n|---|---|---|---|")
        w(f"| {_f(s.get('CL'))} | {_f(s.get('CD'))} | {_f(s.get('CMy', s.get('CMz', s.get('CM'))))} | "
          f"{_f(s.get('L/D', (s.get('CL') or 0) / s['CD'] if s.get('CD') else None), '{:.2f}')} |\n")
    order = ["contour_mach", "contour_pressure", "contour_cp", "contour_mach_wake", "cp_surface", "cf_yplus",
             "surface_cp_top", "surface_cp_bottom", "streamlines_3d", "cp_sections", "span_loading"]
    imgs = res.get("images") or []
    seen = set()
    for key in order:
        for r in imgs:
            b = os.path.splitext(os.path.basename(r))[0]
            if b == key and r not in seen:
                seen.add(r); w(img(r, b.replace("_", " ")))
    for r in imgs:
        b = os.path.basename(r)
        if r not in seen and b not in ("convergence.png", "mesh.png"):
            w(img(r, os.path.splitext(b)[0].replace("_", " ")))
    pol = (S.get("polar") or {}).get("info") or {}
    if pol.get("rows"):
        w("### Polar sweep\n")
        w("| α [°] | CL | CD | CM | converged |\n|---|---|---|---|---|")
        for r in pol["rows"]:
            w(f"| {r['alpha']} | {_f(r['CL'])} | {_f(r['CD'])} | {_f(r['CM'])} | {'yes' if r['converged'] else 'NO'} |")
        w("")
        w(f"*{pol.get('note', '')}*\n")
        w(img("run/polar/polar.png", "Lift curve, drag polar and pitching moment"))
    # ---------------------------------------------------- structure
    w("## Structural results\n")
    if fs:
        w(f"- Model: {fs.get('model')}" + (f", thickness {fs.get('thickness_m', 0)*1e3:.2f} mm" if fs.get('model') == 'shell' else "") +
          f"; material {fs.get('material')} (E = {fs.get('E', 0)/1e9:.1f} GPa, ν = {fs.get('nu')}, allowable "
          f"{fs.get('allowable_Pa', 0)/1e6:.0f} MPa); {fs.get('n_nodes', 0):,} nodes.")
        w(f"- Load case: CFD surface pressure × load factor {fs.get('load_factor')}; root clamped. "
          "One-way coupling, linear static, no inertia relief (conservative for bending).")
        w(f"- Max von Mises: {fs.get('max_von_mises_Pa', 0)/1e6:.1f} MPa (clamp singularity); away from the clamp "
          f"{fs.get('max_von_mises_away_from_clamp_Pa', 0)/1e6:.1f} MPa → **RF = {_f(fs.get('reserve_factor_away_from_clamp'), '{:.2f}')}**.")
        w(f"- Max displacement {fs.get('max_displacement_m', 0)*1e3:.2f} mm; mean tip deflection (z) "
          f"{fs.get('tip_deflection_z_m', 0)*1e3:.2f} mm.\n")
        for r in fea.get("images") or []:
            w(img(r, os.path.splitext(os.path.basename(r))[0].replace("_", " ")))
    else:
        w("Not run for this case.\n")
    # ---------------------------------------------------- limits
    w("## Limitations & next steps\n")
    w("- Mesh sensitivity: rerun at the next mesh level and compare CL/CD before using numbers for decisions.")
    if dv["dim"] == 3:
        w("- 3D wall is not resolved (tetrahedra only); for y+ ≈ 1 RANS rebuild the volume mesh with prism layers "
          "(see the handoff package README).")
    else:
        w("- Fully turbulent: laminar runs / transition at Re < ~5×10⁵ are not captured.")
    if fs:
        w("- Structure: isotropic material, idealised clamp, no ribs/spars unless modelled in the CAD; "
          "no buckling, fatigue or composite ply failure.")
    w("- Rotors / propellers / hover are not supported in this version.\n")
    md = "\n".join(L)
    open(os.path.join(out, "report.md"), "w").write(md)
    open(os.path.join(out, "report.html"), "w").write(to_html(md, out, c["name"]))


def to_html(md, base, title):
    body, in_table, in_list = [], False, False
    for line in md.split("\n"):
        if in_table and not line.startswith("|"):
            body.append("</table>"); in_table = False
        if in_list and not line.startswith("- "):
            body.append("</ul>"); in_list = False
        if line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("|"):
            cells = [x.strip() for x in line.strip("|").split("|")]
            if all(re.fullmatch(r"-+", x) for x in cells):
                continue
            if not in_table:
                body.append("<table>"); in_table = True
                body.append("<tr>" + "".join(f"<th>{_inline(x)}</th>" for x in cells) + "</tr>")
            else:
                body.append("<tr>" + "".join(f"<td>{_inline(x)}</td>" for x in cells) + "</tr>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>"); in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
        elif line.startswith("!["):
            m = re.match(r"!\[(.*?)\]\((.*?)\)", line)
            p = os.path.join(base, m.group(2))
            b64 = base64.b64encode(open(p, "rb").read()).decode() if os.path.exists(p) else ""
            body.append(f'<figure><img alt="{html.escape(m.group(1))}" src="data:image/png;base64,{b64}"></figure>')
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            body.append(f"<p class=cap>{html.escape(line.strip('*'))}</p>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    if in_table: body.append("</table>")
    if in_list: body.append("</ul>")
    css = """body{font:14px/1.5 Segoe UI,Arial,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#1d2733}
h1{border-bottom:3px solid #f5b400;padding-bottom:6px}h2{margin-top:28px;color:#14365c;border-bottom:1px solid #d4d9e0}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #c9d0d8;padding:4px 10px;text-align:left}
th{background:#eef1f5}img{max-width:100%;border:1px solid #d4d9e0}figure{margin:12px 0 2px}.cap{color:#5b6773;font-size:12px;margin-top:0}"""
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)} – report</title><style>{css}</style></head><body>{''.join(body)}</body></html>")


def _inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<i>\1</i>", t)
    return t
