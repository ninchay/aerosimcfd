"""Light-weight readers that turn case files into data for the web viewer.

geometry_info   CAD (STEP/IGES/BREP/STL) -> bounding box, units guess,
                projected planform area, surface triangles for the 3D viewer
read_su2        SU2 mesh -> counts, wall triangles (3D) or a mesh picture (2D)
cfd_surface     surface_flow.vtu -> surface triangles + Cp / Mach / pressure
history         history.csv -> residual and force series
"""
import json, os, math
import numpy as np


# ------------------------------------------------------------------ CAD
def geometry_info(cad, out_json):
    import gmsh
    gmsh.initialize(interruptible=False)   # safe from worker threads
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        ext = os.path.splitext(cad)[1].lower()
        if ext == ".stl":
            gmsh.merge(cad)
        else:
            gmsh.model.occ.importShapes(cad)
            gmsh.model.occ.synchronize()
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        size = max(xmax - xmin, ymax - ymin, zmax - zmin)
        if ext != ".stl":
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.MeshSizeMax", size / 40)
            gmsh.model.mesh.generate(2)
        n_solids = len(gmsh.model.getEntities(3))
        tags, coords, _ = gmsh.model.mesh.getNodes()
        idx = {int(t): i for i, t in enumerate(tags)}
        xyz = coords.reshape(-1, 3)
        tris = []
        for et, _, en in zip(*gmsh.model.mesh.getElements(2)):
            if et == 2:
                tris.append(np.array([idx[int(n)] for n in en]).reshape(-1, 3))
        tris = np.vstack(tris) if tris else np.zeros((0, 3), int)
    finally:
        gmsh.finalize()
    # projected (z) area: half of the total |n_z| area for a closed body
    P = xyz[tris]
    cr = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    proj = 0.25 * np.abs(cr[:, 2]).sum()
    # compact: drop unused nodes
    used = np.unique(tris)
    remap = -np.ones(len(xyz), int); remap[used] = np.arange(len(used))
    xyz, tris = xyz[used], remap[tris]
    units = "mm" if size > 50 else "m"
    info = dict(bbox=[xmin, ymin, zmin, xmax, ymax, zmax], size=size,
                units_guess=units, scale_guess=0.001 if units == "mm" else 1.0,
                n_solids=n_solids, projected_area=proj,
                x_length=xmax - xmin, y_min=ymin, cut_on_y0=abs(ymin) < 1e-6 * max(size, 1e-9),
                n_tris=int(len(tris)))
    json.dump(dict(xyz=np.round(xyz, 6).tolist(), tris=tris.tolist(), fields={}),
              open(out_json, "w"))
    return info


# ------------------------------------------------------------------ SU2 mesh
_NV = {3: 2, 5: 3, 9: 4, 10: 4, 12: 8, 13: 6, 14: 5}


def read_su2(path):
    dim, elems, pts, markers = 2, [], None, {}
    with open(path) as f:
        line = f.readline()
        cur = None
        while line:
            s = line.strip()
            if s.startswith("NDIME="):
                dim = int(s.split("=")[1])
            elif s.startswith("NELEM="):
                n = int(s.split("=")[1])
                types = np.zeros(n, int)
                for i in range(n):
                    v = f.readline().split()
                    types[i] = int(v[0])
                    elems.append(v[1:1 + _NV[int(v[0])]])
                elems = (types, elems)
            elif s.startswith("NPOIN="):
                n = int(s.split("=")[1].split()[0])
                pts = np.array([f.readline().split()[:dim] for _ in range(n)], float)
            elif s.startswith("MARKER_TAG="):
                cur = s.split("=")[1].strip()
            elif s.startswith("MARKER_ELEMS=") and cur:
                n = int(s.split("=")[1])
                markers[cur] = [list(map(int, f.readline().split())) for _ in range(n)]
            line = f.readline()
    return dim, elems, pts, markers


def mesh_view(su2, wall, out_json, out_png, chord=1.0):
    dim, (types, elems), pts, markers = read_su2(su2)
    counts = {}
    for t in types:
        counts[t] = counts.get(t, 0) + 1
    names = {5: "triangles", 9: "quads", 10: "tetrahedra", 12: "hexahedra",
             13: "prisms", 14: "pyramids"}
    info = dict(dim=dim, n_points=int(len(pts)), n_cells=int(len(types)),
                cells={names.get(k, str(k)): v for k, v in counts.items()},
                markers={k: len(v) for k, v in markers.items()})
    if dim == 3:
        w = markers.get(wall) or next(iter(markers.values()))
        tri = np.array([e[1:4] for e in w if e[0] == 5])
        used = np.unique(tri)
        remap = -np.ones(len(pts), int); remap[used] = np.arange(len(used))
        json.dump(dict(xyz=np.round(pts[used], 6).tolist(), tris=remap[tri].tolist(),
                       fields={}, wire=True), open(out_json, "w"))
        info["wall_faces"] = int(len(tri))
    else:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection
        polys = [pts[list(map(int, e))] for e in elems]
        fig, ax = plt.subplots(1, 2, figsize=(13, 5), dpi=120)
        for a, (xl, yl, ttl) in zip(ax, [((-0.6 * chord, 1.8 * chord), (-0.6 * chord, 0.6 * chord), "Near field"),
                                        ((-0.02 * chord, 0.06 * chord), (-0.03 * chord, 0.03 * chord), "Leading edge")]):
            sel = [p for p in polys if (p[:, 0].min() < xl[1] and p[:, 0].max() > xl[0]
                                         and p[:, 1].min() < yl[1] and p[:, 1].max() > yl[0])]
            a.add_collection(PolyCollection(sel, facecolors="none", edgecolors="#1f3b73", linewidths=0.25))
            a.set_xlim(*xl); a.set_ylim(*yl); a.set_aspect("equal"); a.set_title(ttl)
        fig.tight_layout(); fig.savefig(out_png); plt.close(fig)
    return info


# ------------------------------------------------------------------ CFD surface
def cfd_surface(run, out_json):
    import pyvista as pv          # SU2 writes raw appended VTU, which meshio cannot read
    s = pv.read(os.path.join(run, "surface_flow.vtu"))
    if "Pressure_Coefficient" not in s.point_data and s.cell_data:
        s = s.cell_data_to_point_data()
    s = s.extract_surface().triangulate()
    tris = s.faces.reshape(-1, 4)[:, 1:]
    fields = {}
    for key, lab in (("Pressure_Coefficient", "Cp"), ("Pressure", "Pressure [Pa]"),
                     ("Mach", "Mach"), ("Skin_Friction_Coefficient", "|Cf|"), ("Y_Plus", "y+")):
        if key in s.point_data:
            v = np.asarray(s.point_data[key])
            if v.ndim > 1:
                v = np.linalg.norm(v, axis=1)
            fields[lab] = np.round(v, 5).tolist()
    json.dump(dict(xyz=np.round(np.asarray(s.points), 6).tolist(), tris=tris.tolist(), fields=fields),
              open(out_json, "w"))


# ------------------------------------------------------------------ history
def history(run):
    p = os.path.join(run, "history.csv")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        head = [c.strip().strip('"').strip() for c in f.readline().split(",")]
        rows = []
        for line in f:
            v = line.split(",")
            if len(v) == len(head):
                try:
                    rows.append([float(x) for x in v])
                except ValueError:
                    pass
    if not rows:
        return dict(columns=head, data={})
    A = np.array(rows)
    if len(A) > 1500:                      # thin long histories for the browser
        A = A[np.unique(np.r_[np.linspace(0, len(A) - 1, 1500).astype(int), len(A) - 1])]
    keep = [i for i, c in enumerate(head) if c.startswith("rms[") or c in ("Inner_Iter", "CL", "CD", "CMy", "CMz", "Avg_CFL")]
    return dict(columns=[head[i] for i in keep], data={head[i]: A[:, i].round(7).tolist() for i in keep})
