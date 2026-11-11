#!/usr/bin/env python3
"""2D RANS mesh around an airfoil: quad boundary layer (y+ ~ 1) + triangles,
circular farfield. Writes an SU2 mesh with markers `airfoil` and `farfield`.

Input: airfoil coordinates in Selig order (TE -> upper -> LE -> lower -> TE),
already scaled to the physical chord (see make_naca_wing.py --dat, or any
UIUC .dat file; a header line is skipped automatically).

Examples
  python mesh_2d_airfoil.py naca0012.dat -o mesh.su2 --y1 4e-6
  python mesh_2d_airfoil.py my.dat -o mesh.su2 --y1 1e-5 --level fine
Use flow_conditions.py to get --y1 for your Reynolds number.
"""
import argparse
import numpy as np

LEVELS = {  # surface points, BL growth, far-field factor, wake refinement size
    "coarse": dict(n_surf=180, ratio=1.20, far_h=8.0, wake_h=0.04),
    "medium": dict(n_surf=300, ratio=1.15, far_h=5.0, wake_h=0.02),
    "fine":   dict(n_surf=480, ratio=1.10, far_h=4.0, wake_h=0.012),
}


def read_dat(path):
    rows = []
    for line in open(path):
        try:
            x, y = map(float, line.split()[:2]); rows.append((x, y))
        except ValueError:
            continue
    xy = np.array(rows)
    if np.allclose(xy[0], xy[-1]):
        xy = xy[:-1]
    return xy


def resample(xy, n):
    """Cosine-clustered resampling along arc length (dense at LE and TE)."""
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(np.vstack([xy, xy[:1]]), axis=0).T))]
    closed = np.vstack([xy, xy[:1]])
    ile = int(np.argmin(xy[:, 0]))
    out = []
    for a, b in ((0, s[ile]), (s[ile], s[-1])):
        t = a + (b - a) * 0.5 * (1 - np.cos(np.linspace(0, np.pi, n // 2 + 1)))
        out.append(np.c_[np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])][:-1])
    return np.vstack(out), n // 2


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dat")
    ap.add_argument("-o", "--out", default="mesh.su2")
    ap.add_argument("--y1", type=float, required=True, help="first cell height [m]")
    ap.add_argument("--bl-thick", type=float, help="quad layer thickness [m] (default 4%% chord)")
    ap.add_argument("--farfield", type=float, default=100.0, help="farfield radius in chords")
    ap.add_argument("--level", choices=LEVELS, default="medium")
    a = ap.parse_args()
    L = LEVELS[a.level]

    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("airfoil2d")
    geo = gmsh.model.geo
    xy, ile = resample(read_dat(a.dat), L["n_surf"])
    chord = xy[:, 0].max() - xy[:, 0].min()
    xc = xy[:, 0].min() + 0.25 * chord
    pts = [geo.addPoint(x, y, 0) for x, y in xy]
    up = geo.addSpline(pts[:ile + 1])
    lo = geo.addSpline(pts[ile:] + [pts[0]])
    R = a.farfield * chord
    c0 = geo.addPoint(xc, 0, 0)
    far_pts = [geo.addPoint(xc + R * np.cos(t), R * np.sin(t), 0, L["far_h"] * R / 10)
               for t in (0, np.pi / 2, np.pi, 1.5 * np.pi)]
    arcs = [geo.addCircleArc(far_pts[i], c0, far_pts[(i + 1) % 4]) for i in range(4)]
    outer = geo.addCurveLoop(arcs)
    inner = geo.addCurveLoop([up, lo])
    surf = geo.addPlaneSurface([outer, inner])
    geo.synchronize()
    # Gmsh places curve nodes by the size field, not at the spline points, so
    # fix the surface distribution explicitly: clustered at LE and TE.
    for c in (up, lo):
        gmsh.model.mesh.setTransfiniteCurve(c, L["n_surf"] // 2 + 1, "Bump", 0.12)
    gmsh.model.addPhysicalGroup(1, [up, lo], name="airfoil")
    gmsh.model.addPhysicalGroup(1, arcs, name="farfield")
    gmsh.model.addPhysicalGroup(2, [surf], name="fluid")

    f = gmsh.model.mesh.field
    bl = f.add("BoundaryLayer")
    f.setNumbers(bl, "CurvesList", [up, lo])
    f.setNumber(bl, "Size", a.y1)
    f.setNumber(bl, "Ratio", L["ratio"])
    f.setNumber(bl, "Thickness", a.bl_thick or 0.04 * chord)
    f.setNumber(bl, "SizeFar", 0.01 * chord)
    f.setNumber(bl, "Quads", 1)
    f.setNumbers(bl, "FanPointsList", [pts[0]])      # sharp TE fan
    f.setAsBoundaryLayer(bl)
    # Near-body + wake refinement via a box behind the TE
    wake = f.add("Box")
    f.setNumber(wake, "VIn", L["wake_h"] * chord); f.setNumber(wake, "VOut", 1e9)
    f.setNumber(wake, "XMin", xy[:, 0].min() - 0.2 * chord)
    f.setNumber(wake, "XMax", xy[:, 0].max() + 3.0 * chord)
    f.setNumber(wake, "YMin", -0.3 * chord); f.setNumber(wake, "YMax", 0.3 * chord)
    f.setNumber(wake, "Thickness", 2.0 * chord)
    dist = f.add("Distance"); f.setNumbers(dist, "CurvesList", [up, lo])
    f.setNumber(dist, "Sampling", 400)
    grow = f.add("MathEval")
    f.setString(grow, "F", f"{chord/L['n_surf']*2:.6g} + 0.12*F{dist}")
    mn = f.add("Min"); f.setNumbers(mn, "FieldsList", [wake, grow])
    f.setAsBackgroundMesh(mn)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.model.mesh.generate(2)
    gmsh.option.setNumber("Mesh.SaveAll", 0)
    gmsh.write(a.out)
    types, tags, _ = gmsh.model.mesh.getElements(2)
    n = sum(len(t) for t in tags)
    gmsh.finalize()
    print(f"wrote {a.out}: {n} cells, chord={chord:.4g} m, y1={a.y1:.3g} m")


if __name__ == "__main__":
    main()
