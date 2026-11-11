#!/usr/bin/env python3
"""One-way fluid -> structure coupling: map SU2 surface pressure onto a
structural model of the same CAD and solve linear static FEA with CalculiX.

Structural model (--model):
  solid  quadratic tetrahedra (C3D10) filling the CAD solid. Right for solid or
         thick parts (small UAV foam/composite-filled wings, brackets, spars)
  shell  quadratic triangular shells (S6) on the outer surface with a uniform
         --thickness: a monocoque skin. Right for thin-walled skins; it ignores
         internal spars/ribs unless they are in the CAD as surfaces.
  auto   shell if the part is thin-walled by the user's description, else solid
         (the skill decides; this script just needs the explicit choice)

Loads: gauge pressure (p - p_inf) from the CFD surface, interpolated to every
structural surface face (inverse-distance, 8 nearest CFD points), turned into
consistent nodal forces (6-node triangle: midside nodes carry A/3 each). The
sum of applied forces is printed and compared with the CFD force so mapping
errors are caught. Optional --load-factor (e.g. 1.5 x limit for ultimate).

Boundary condition: all nodes with y <= --clamp-y are fixed (wing root
clamp). Use --clamp-axis/--clamp-y for other parts.

Outputs (in --out dir): model.inp, CalculiX results, fea_summary.json,
stress / displacement images, nodal results CSV.

Example
  python fea_from_cfd.py wing.step --cfd-run run3d --p-inf 22632 \
      --model shell --thickness 0.0015 --material Al7075-T6 --out fea
"""
import argparse, json, os, subprocess
import numpy as np

MATERIALS = {  # E [Pa], nu, rho [kg/m3], yield/allowable [Pa]
    "Al7075-T6": (71.7e9, 0.33, 2810, 503e6),
    "Al2024-T3": (73.1e9, 0.33, 2780, 345e6),
    "Al6061-T6": (68.9e9, 0.33, 2700, 276e6),
    "Ti-6Al-4V": (113.8e9, 0.342, 4430, 880e6),
    "Steel-4130": (205e9, 0.29, 7850, 460e6),
    "CFRP-quasi-iso": (50e9, 0.30, 1600, 450e6),   # isotropic approximation!
    "GFRP-quasi-iso": (20e9, 0.25, 1900, 250e6),
    "PLA-print": (3.5e9, 0.36, 1250, 50e6),
}
TRI6_DIRECT = {9: 6, 2: 3}          # gmsh type ids: 9 = tri6, 2 = tri3
TET10 = 11


def mesh_structure(cad, model, h, scale):
    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Geometry.OCCScaling", scale)
    gmsh.model.add("struct")
    gmsh.model.occ.importShapes(cad); gmsh.model.occ.synchronize()
    vols = gmsh.model.getEntities(3)
    if not vols:
        raise SystemExit("structural CAD must be a solid")
    gmsh.option.setNumber("Mesh.MeshSizeMax", h)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h / 5)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
    bnd = gmsh.model.getBoundary(vols, oriented=False, combined=True)
    gmsh.model.mesh.generate(3 if model == "solid" else 2)
    nt, xyz, _ = gmsh.model.mesh.getNodes()
    xyz = xyz.reshape(-1, 3)
    pos = {t: i for i, t in enumerate(nt)}
    vtags = [v for _, v in vols]
    faces = []                        # (6 node tags, outward sign) per boundary tri
    for _, s in bnd:
        types, _, conn = gmsh.model.mesh.getElements(2, s)
        rows = [c.reshape(-1, 6) for t, c in zip(types, conn) if t == 9]
        if not rows:
            continue
        rows = np.vstack(rows)
        # Outward test per surface: step a little along the element normal from a
        # few face centroids and ask the CAD kernel whether we are still inside.
        votes = 0
        for row in rows[:: max(1, len(rows) // 7)][:7]:
            P = xyz[[pos[t] for t in row[:3]]]
            n = np.cross(P[1] - P[0], P[2] - P[0]); n /= np.linalg.norm(n)
            eps = 0.2 * min(np.linalg.norm(P[1] - P[0]), np.linalg.norm(P[2] - P[0]))
            c = P.mean(axis=0)
            inside_back = any(gmsh.model.isInside(3, v, list(c - eps * n)) for v in vtags)
            inside_fwd = any(gmsh.model.isInside(3, v, list(c + eps * n)) for v in vtags)
            votes += (1 if inside_back and not inside_fwd else
                      -1 if inside_fwd and not inside_back else 0)
        sg = 1 if votes >= 0 else -1
        faces += [(row, sg) for row in rows]
    vol_el = []
    if model == "solid":
        for _, v in vols:
            types, _, conn = gmsh.model.mesh.getElements(3, v)
            for t, c in zip(types, conn):
                if t == TET10:
                    vol_el.append(c.reshape(-1, 10))
        vol_el = np.vstack(vol_el)
    gmsh.finalize()
    return nt.astype(int), xyz, faces, vol_el


def tri_geom(P):
    n = np.cross(P[1] - P[0], P[2] - P[0])
    A = 0.5 * np.linalg.norm(n)
    return n / (2 * A), A, P[:3].mean(axis=0)


def read_cfd_surface(run, p_inf):
    import pyvista as pv
    s = pv.read(os.path.join(run, "surface_flow.vtu"))
    if "Pressure" not in s.point_data:
        s = s.cell_data_to_point_data()
    return s.points, s.point_data["Pressure"] - p_inf


def farfield_pressure(run):
    """Median static pressure on the outer 10 % of the CFD domain."""
    import pyvista as pv
    v = pv.read(os.path.join(run, "flow.vtu"))
    p = np.asarray(v.point_data["Pressure"])
    c = np.asarray(pv.read(os.path.join(run, "surface_flow.vtu")).center)
    d = np.linalg.norm(v.points - c, axis=1)
    return float(np.median(p[d > np.percentile(d, 90)]))


def write_inp(path, nodes, xyz, faces, vol_el, model, thickness, mat, forces, fixed):
    E, nu, rho, _ = mat
    tid = {t: i for i, t in enumerate(nodes)}
    with open(path, "w") as f:
        f.write("*HEADING\nfea_from_cfd.py one-way FSI\n*NODE, NSET=NALL\n")
        for t, p in zip(nodes, xyz):
            f.write(f"{t}, {p[0]:.9g}, {p[1]:.9g}, {p[2]:.9g}\n")
        if model == "solid":
            f.write("*ELEMENT, TYPE=C3D10, ELSET=EALL\n")
            # gmsh tet10 -> CalculiX C3D10: last two midside nodes swapped
            for i, e in enumerate(vol_el, 1):
                e = e[[0, 1, 2, 3, 4, 5, 6, 7, 9, 8]]
                f.write(f"{i}, " + ", ".join(map(str, e)) + "\n")
        else:
            f.write("*ELEMENT, TYPE=S6, ELSET=EALL\n")
            for i, (e, sg) in enumerate(faces, 1):
                e = e if sg > 0 else e[[0, 2, 1, 5, 4, 3]]   # outward normals
                f.write(f"{i}, " + ", ".join(map(str, e)) + "\n")
        f.write("*NSET, NSET=FIXED\n")
        for i in range(0, len(fixed), 12):
            f.write(", ".join(map(str, fixed[i:i + 12])) + ",\n")
        f.write(f"*MATERIAL, NAME=MAT\n*ELASTIC\n{E:.6g}, {nu}\n*DENSITY\n{rho}\n")
        if model == "solid":
            f.write("*SOLID SECTION, ELSET=EALL, MATERIAL=MAT\n")
        else:
            f.write(f"*SHELL SECTION, ELSET=EALL, MATERIAL=MAT, OFFSET=-0.5\n{thickness}\n")
        f.write("*BOUNDARY\nFIXED, 1, 6\n" if model == "shell" else "*BOUNDARY\nFIXED, 1, 3\n")
        f.write("*STEP\n*STATIC\n*CLOAD\n")
        for t, F in forces.items():
            for d in range(3):
                if abs(F[d]) > 0:
                    f.write(f"{t}, {d+1}, {F[d]:.8g}\n")
        f.write("*NODE FILE\nU, RF\n*EL FILE\nS, E\n*END STEP\n")


def parse_frd(path):
    """Return dict block -> {node: values}: COORD (node coordinates) and the
    result blocks DISP, STRESS, TOSTRAIN, FORC. Shell elements are written on
    CalculiX's expanded 3D nodes (new ids), so coordinates are needed."""
    out, cur = {}, None
    for line in open(path):
        if line.startswith("    2C"):
            cur = "COORD"; out[cur] = {}
        elif line.startswith(" -4"):
            cur = line[5:13].strip(); out[cur] = {}
        elif line.startswith(" -1") and cur:
            nid = int(line[3:13])
            n = (len(line.rstrip()) - 13) // 12
            out[cur][nid] = [float(line[13 + 12 * i:25 + 12 * i]) for i in range(n)]
        elif line.startswith(" -3"):
            cur = None
    return out


def von_mises(s):
    sxx, syy, szz, sxy, syz, szx = s.T
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
                   + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))


def render(xyz, tris, values, label, path, disp=None, scale=1.0):
    import pyvista as pv
    pv.OFF_SCREEN = True
    pts = xyz + (disp * scale if disp is not None else 0)
    faces = np.hstack([np.full((len(tris), 1), 3), tris]).ravel()
    m = pv.PolyData(pts, faces); m.point_data[label] = values
    p = pv.Plotter(off_screen=True, window_size=(1400, 900))
    if disp is not None and scale != 1.0:
        p.add_mesh(pv.PolyData(xyz, faces), style="wireframe", color="grey", opacity=0.25)
    p.add_mesh(m, scalars=label, cmap="jet", scalar_bar_args=dict(title=label))
    p.camera_position = "iso"; p.camera.azimuth = -60; p.camera.elevation = 20
    if disp is not None and scale != 1.0:
        p.add_text(f"deformed x{scale:.0f}", font_size=11)
    p.screenshot(path); p.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cad")
    ap.add_argument("--cfd-run", required=True, help="SU2 run dir with surface_flow.vtu")
    ap.add_argument("--p-inf", type=float,
                    help="freestream static pressure [Pa]; default: read from the far field "
                         "of the CFD solution (0 for incompressible gauge pressure)")
    ap.add_argument("--model", choices=["solid", "shell"], required=True)
    ap.add_argument("--thickness", type=float, help="shell thickness [m]")
    ap.add_argument("--material", default="Al7075-T6", choices=MATERIALS)
    ap.add_argument("--E", type=float); ap.add_argument("--nu", type=float)
    ap.add_argument("--yield-stress", type=float, help="allowable [Pa]")
    ap.add_argument("--h", type=float, help="structural element size [m]")
    ap.add_argument("--scale", type=float, default=1.0, help="CAD units -> m")
    ap.add_argument("--clamp-axis", default="y", choices="xyz")
    ap.add_argument("--clamp-y", type=float, default=1e-6,
                    help="fix nodes with coordinate <= this value on --clamp-axis [m]")
    ap.add_argument("--load-factor", type=float, default=1.0)
    ap.add_argument("--mirror-cfd", action="store_true",
                    help="CFD was a half model but the structure is full span")
    ap.add_argument("--out", default="fea")
    a = ap.parse_args()
    if a.model == "shell" and not a.thickness:
        ap.error("--model shell needs --thickness")
    os.makedirs(a.out, exist_ok=True)
    mat = list(MATERIALS[a.material])
    if a.E: mat[0] = a.E
    if a.nu: mat[1] = a.nu
    if a.yield_stress: mat[3] = a.yield_stress

    if a.p_inf is None:
        a.p_inf = farfield_pressure(a.cfd_run)
        print(f"p_inf from CFD far field: {a.p_inf:.6g} Pa")
    cp_xyz, gauge = read_cfd_surface(a.cfd_run, a.p_inf)
    if a.mirror_cfd:
        m = cp_xyz.copy(); m[:, 1] *= -1
        cp_xyz = np.vstack([cp_xyz, m]); gauge = np.r_[gauge, gauge]
    span = np.ptp(cp_xyz, axis=0).max()
    h = a.h or span / 60
    nodes, xyz, faces, vol_el = mesh_structure(a.cad, a.model, h, a.scale)
    tid = {t: i for i, t in enumerate(nodes)}
    from scipy.spatial import cKDTree
    tree = cKDTree(cp_xyz)
    forces, Ftot, dmax = {}, np.zeros(3), 0.0
    ax = "xyz".index(a.clamp_axis)
    for e, sg in faces:
        P = xyz[[tid[t] for t in e]]
        if np.all(P[:3, ax] <= a.clamp_y):     # root / clamp face: not wetted
            continue
        n, A, c = tri_geom(P)
        n *= sg
        d, j = tree.query(c, k=8)
        dmax = max(dmax, d[0])
        w = 1 / np.maximum(d, 1e-12) ** 2
        p = float(np.sum(w * gauge[j]) / w.sum()) * a.load_factor
        F = -p * A * n                                 # pressure pushes inward
        Ftot += F
        for t in e[3:]:                                # tri6 consistent load
            forces.setdefault(int(t), np.zeros(3))
            forces[int(t)] += F / 3
    ax = "xyz".index(a.clamp_axis)
    fixed = [int(t) for t, p in zip(nodes, xyz) if p[ax] <= a.clamp_y]
    if not fixed:
        raise SystemExit("no nodes found for the clamp; check --clamp-axis/--clamp-y")
    if a.model == "shell":   # only nodes actually used by shell elements
        used = set(np.concatenate([e for e, _ in faces]).tolist())
        keep = np.array([t in used for t in nodes])
        nodes, xyz = nodes[keep], xyz[keep]
        fixed = [t for t in fixed if t in used]
    inp = os.path.join(a.out, "model.inp")
    write_inp(inp, nodes, xyz, faces, vol_el, a.model, a.thickness, mat, forces, fixed)
    print(f"structure: {len(nodes)} nodes, "
          f"{len(vol_el) if a.model=='solid' else len(faces)} elements, {len(fixed)} clamped")
    print(f"applied aero force [N]: Fx={Ftot[0]:.4g} Fy={Ftot[1]:.4g} Fz={Ftot[2]:.4g}; "
          f"max CFD->FEA mapping distance {dmax:.3g} m")
    r = subprocess.run(["ccx", "-i", "model"], cwd=a.out, capture_output=True, text=True)
    open(os.path.join(a.out, "ccx.log"), "w").write(r.stdout + r.stderr)
    if r.returncode != 0 or not os.path.exists(os.path.join(a.out, "model.frd")):
        raise SystemExit("CalculiX failed – see ccx.log")
    res = parse_frd(os.path.join(a.out, "model.frd"))
    ids = np.array(sorted(res["DISP"]))
    C = np.array([res["COORD"][i] for i in ids])
    Ud = np.array([res["DISP"][i][:3] for i in ids])
    Sd = np.array([res["STRESS"][i][:6] for i in ids])
    Ekey = "TOSTRAIN" if "TOSTRAIN" in res else ("STRAIN" if "STRAIN" in res else None)
    Ed = np.array([res[Ekey][i][:6] for i in ids]) if Ekey else None
    vm_all = von_mises(Sd)
    if a.model == "solid":
        idx_ = {i: k for k, i in enumerate(ids)}
        sel = [idx_[int(t)] for t in nodes]
        U, S = Ud[sel], Sd[sel]
        vm_node = vm_all[sel]
        Ev = Ed[sel] if Ed is not None else None
    else:
        # each shell node has expanded partners within one thickness:
        # report the worst (top/bottom fibre) stress and the mean displacement
        tr = cKDTree(C)
        nb = tr.query_ball_point(xyz, r=1.05 * a.thickness)
        U = np.array([Ud[j].mean(axis=0) if j else np.zeros(3) for j in nb])
        k = [j[int(np.argmax(vm_all[j]))] if j else 0 for j in nb]
        S, vm_node = Sd[k], vm_all[k]
        Ev = Ed[k] if Ed is not None else None
    vm = vm_node
    umag = np.linalg.norm(U, axis=1)
    rf = res.get("FORC", {})
    # reactions = FORC summed over the clamped nodes only (expanded ids for shells)
    Rsum = np.full(3, np.nan)
    if rf:
        clamp_ids = [i for i, c in zip(ids, C) if c[ax] <= a.clamp_y + 1.05 * (a.thickness or 0)
                     and i in rf]
        Rsum = np.sum([rf[i][:3] for i in clamp_ids], axis=0)
    # strength away from the clamp singularity (skip the first 5 % of the part)
    ext = np.ptp(xyz[:, ax])
    away = xyz[:, ax] > xyz[:, ax].min() + 0.05 * ext
    vm_away = float(vm[away].max()) if away.any() else float(vm.max())
    tip = xyz[:, 1] > xyz[:, 1].max() - 0.01 * np.ptp(xyz[:, 1])
    # surface triangles for pictures (corner nodes only)
    idx = {t: i for i, t in enumerate(nodes)}
    tris = np.array([[idx[t] for t in e[:3]] for e, _ in faces if all(t in idx for t in e[:3])])
    sc = 0.1 * span / umag.max() if umag.max() > 0 else 1
    sc = float(max(1.0, round(sc)))
    render(xyz, tris, vm / 1e6, "von Mises [MPa]", os.path.join(a.out, "stress_von_mises.png"))
    render(xyz, tris, umag * 1e3, "|u| [mm]", os.path.join(a.out, "displacement.png"), U, sc)
    if Ev is not None:
        e = Ev.T; tr_ = (e[0] + e[1] + e[2]) / 3
        dev2 = (e[0]-tr_)**2 + (e[1]-tr_)**2 + (e[2]-tr_)**2 + 2*(e[3]**2 + e[4]**2 + e[5]**2)
        evm = np.sqrt(2.0 / 3.0 * dev2)          # von Mises equivalent strain
        render(xyz, tris, evm * 1e6, "equiv. strain [µε]", os.path.join(a.out, "strain.png"))
    # [AeroSim Workbench] surface data for the interactive 3D viewer
    try:
        view = dict(xyz=np.round(xyz, 6).tolist(), tris=tris.astype(int).tolist(),
                    fields={"von Mises [MPa]": np.round(vm / 1e6, 4).tolist(),
                            "|u| [mm]": np.round(umag * 1e3, 5).tolist()},
                    disp=np.round(U, 7).tolist(), disp_scale=sc)
        if Ev is not None:
            view["fields"]["equiv. strain [µε]"] = np.round(evm * 1e6, 3).tolist()
        json.dump(view, open(os.path.join(a.out, "viewer.json"), "w"))
    except Exception as ex:
        print("viewer export skipped:", ex)
    np.savetxt(os.path.join(a.out, "nodal_results.csv"),
               np.c_[nodes, xyz, U, S, vm], delimiter=",",
               header="node,x,y,z,ux,uy,uz,sxx,syy,szz,sxy,syz,szx,von_mises", comments="")
    summary = dict(model=a.model, material=a.material, E=mat[0], nu=mat[1],
                   allowable_Pa=mat[3], thickness_m=a.thickness, load_factor=a.load_factor,
                   n_nodes=int(len(nodes)), applied_force_N=Ftot.tolist(),
                   reaction_force_N=Rsum.tolist() if rf else None,
                   max_von_mises_Pa=float(vm.max()),
                   max_von_mises_away_from_clamp_Pa=vm_away,
                   force_balance_error=float(np.linalg.norm(Ftot + Rsum) / np.linalg.norm(Ftot))
                   if rf else None,
                   max_von_mises_location=xyz[int(vm.argmax())].tolist(),
                   max_displacement_m=float(umag.max()),
                   max_displacement_location=xyz[int(umag.argmax())].tolist(),
                   tip_deflection_z_m=float(U[tip, 2].mean()),
                   reserve_factor_away_from_clamp=float(mat[3] / vm_away) if vm_away > 0 else None,
                   mapping_max_distance_m=float(dmax),
                   note=("peak stress at the clamp is a singularity of the idealised "
                         "fixed support; judge strength a short distance away"))
    json.dump(summary, open(os.path.join(a.out, "fea_summary.json"), "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
