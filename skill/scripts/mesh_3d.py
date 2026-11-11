#!/usr/bin/env python3
"""3D external-flow mesh around a CAD body (STEP/IGES/BREP or STL) for SU2.

Builds a box far-field around the body, removes the body, and meshes the
fluid with tetrahedra refined toward the wall (curvature-aware surface mesh,
distance-based growth). Prints a cell-count estimate first and stops if it is
above --max-cells, so a run never silently exhausts memory.

Markers written:  <wall> (body), farfield, symmetry (only with --half)

  STEP/IGES/BREP  closed solid(s); multiple solids are fused. Supports --half:
                  the body must be cut at y = 0 (wing root / aircraft plane of
                  symmetry on y = 0); the domain keeps y >= 0.
  STL             watertight, full body (no --half). Surface triangles are
                  re-classified into patches and remeshed.

Wall treatment: tetrahedra only, so the first cell is ~0.3-0.5 x --wall-h.
Run EULER, or RANS with --wall-functions sized for y+ 30-100 (use
flow_conditions.py --yplus 50 and pass about 2-3 x that height as --wall-h
only if you can afford it; otherwise accept y+ in the hundreds and say so).
Fully resolved y+~1 prism layers are not produced here; see
references/meshing.md for the hand-off route.

Examples
  python mesh_3d.py wing.step --half --wall wing -o wing.su2 --level coarse
  python mesh_3d.py uav.stl --scale 0.001 --wall aircraft -o uav.su2 --level medium
"""
import argparse, math
import numpy as np

LEVELS = {  # wall size (x lref), growth rate, far size (x lref), curvature pts/2pi
    "coarse": dict(h_surf=1 / 40, grow=0.25, h_far=4.0, curv=16),
    "medium": dict(h_surf=1 / 70, grow=0.18, h_far=3.0, curv=24),
    "fine":   dict(h_surf=1 / 120, grow=0.12, h_far=2.0, curv=36),
}


def classify(gmsh, box, tol):
    """Split boundary surfaces of the fluid volume into farfield / symmetry / wall."""
    far, sym, wall = [], [], []
    xmin, ymin, zmin, xmax, ymax, zmax = box
    on = lambda lo, hi, v: abs(lo - v) < tol and abs(hi - v) < tol
    for _, s in gmsh.model.getBoundary(gmsh.model.getEntities(3), oriented=False):
        b = gmsh.model.getBoundingBox(2, s)
        if on(b[1], b[4], ymin):
            sym.append(s)
        elif (on(b[0], b[3], xmin) or on(b[0], b[3], xmax) or on(b[1], b[4], ymax)
              or on(b[2], b[5], zmin) or on(b[2], b[5], zmax)):
            far.append(s)
        else:
            wall.append(s)
    return far, sym, wall


def geo_box(geo, b):
    """Box from the built-in kernel (needed when the body is a discrete STL)."""
    x0, y0, z0, x1, y1, z1 = b
    P = [geo.addPoint(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    # point index = 4*k + 2*j + i  (i: x, j: y, k: z)
    p = lambda i, j, k: P[4 * k + 2 * j + i]
    def quad(a, b_, c, d):
        l = [geo.addLine(a, b_), geo.addLine(b_, c), geo.addLine(c, d), geo.addLine(d, a)]
        return geo.addPlaneSurface([geo.addCurveLoop(l)])
    S = [quad(p(0,0,0), p(1,0,0), p(1,1,0), p(0,1,0)), quad(p(0,0,1), p(1,0,1), p(1,1,1), p(0,1,1)),
         quad(p(0,0,0), p(1,0,0), p(1,0,1), p(0,0,1)), quad(p(0,1,0), p(1,1,0), p(1,1,1), p(0,1,1)),
         quad(p(0,0,0), p(0,1,0), p(0,1,1), p(0,0,1)), quad(p(1,0,0), p(1,1,0), p(1,1,1), p(1,0,1))]
    geo.removeAllDuplicates()
    return S


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cad", help="STEP/IGES/BREP/STL file")
    ap.add_argument("-o", "--out", default="mesh3d.su2")
    ap.add_argument("--wall", default="wall", help="marker name for the body")
    ap.add_argument("--scale", type=float, default=1.0, help="CAD units -> m (mm: 0.001)")
    ap.add_argument("--half", action="store_true", help="half model, symmetry at y=0")
    ap.add_argument("--lref", type=float, help="reference length (default: body x-length)")
    ap.add_argument("--farfield", type=float, default=12.0,
                    help="far-field distance in reference lengths")
    ap.add_argument("--level", choices=LEVELS, default="coarse")
    ap.add_argument("--wall-h", type=float, help="override wall surface cell size [m]")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-cells", type=float, default=2.5e6,
                    help="stop before 3D meshing if the estimate is above this")
    a = ap.parse_args()
    L = LEVELS[a.level]
    is_stl = a.cad.lower().endswith(".stl")
    if is_stl and a.half:
        ap.error("--half is only supported for STEP/IGES/BREP solids")

    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 1)
    gmsh.option.setNumber("General.NumThreads", a.threads)
    gmsh.model.add("ext3d")
    if is_stl:
        gmsh.merge(a.cad)
        if a.scale != 1.0:
            gmsh.model.mesh.affineTransform([a.scale, 0, 0, 0, 0, a.scale, 0, 0, 0, 0, a.scale, 0])
        gmsh.model.mesh.classifySurfaces(40 * math.pi / 180, True, True, math.pi)
        gmsh.model.mesh.createGeometry()
        gmsh.model.geo.synchronize()
        body = [s for _, s in gmsh.model.getEntities(2)]
    else:
        gmsh.option.setNumber("Geometry.OCCScaling", a.scale)
        ents = gmsh.model.occ.importShapes(a.cad)
        gmsh.model.occ.synchronize()
        vols = [t for d, t in ents if d == 3]
        if not vols:
            raise SystemExit("CAD has no solid; export a closed solid (or a watertight STL)")
        if len(vols) > 1:
            gmsh.model.occ.fuse([(3, vols[0])], [(3, v) for v in vols[1:]])
            gmsh.model.occ.synchronize()
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
    Lx, span, H = xmax - xmin, ymax - ymin, zmax - zmin
    lref = a.lref or Lx
    F = a.farfield * lref
    h_wall = a.wall_h or L["h_surf"] * lref
    h_far = L["h_far"] * lref
    if a.half and abs(ymin) > 1e-3 * lref:
        raise SystemExit(f"--half needs the body cut at y=0 (min y = {ymin:.4g} m)")
    box = (xmin - F, 0.0 if a.half else ymin - F, zmin - F,
           xmax + 1.5 * F, ymax + F, zmax + F)
    print(f"body bbox: L={Lx:.4g} m, span={span:.4g} m, height={H:.4g} m")

    # cell estimate: wetted area ~ 2*planform, shells growing from the wall
    area = 2.2 * Lx * span
    r = np.linspace(0, F, 400)
    hh = np.minimum(h_far, h_wall + L["grow"] * r)
    shell = area + 4 * r * (Lx + span) + (2 if a.half else 4) * math.pi * r ** 2
    est = float(np.trapezoid(shell / hh ** 3, r)) * 6
    print(f"lref={lref:.4g} m  wall cell={h_wall:.4g} m  far cell={h_far:.4g} m  "
          f"estimated ~{est/1e6:.2f} M tetrahedra")
    if est > a.max_cells:
        raise SystemExit(f"estimate {est:.3g} > --max-cells {a.max_cells:.3g}: use a coarser "
                         "--level / larger --wall-h, or raise --max-cells knowingly")

    if is_stl:
        geo = gmsh.model.geo
        S = geo_box(geo, box)
        vol = geo.addVolume([geo.addSurfaceLoop(S), geo.addSurfaceLoop(body)])
        geo.synchronize()
        far, sym, wall = S, [], body
    else:
        occ = gmsh.model.occ
        bx = occ.addBox(box[0], box[1], box[2], box[3] - box[0], box[4] - box[1], box[5] - box[2])
        occ.cut([(3, bx)], [(3, v) for _, v in gmsh.model.getEntities(3) if v != bx])
        occ.synchronize()
        far, sym, wall = classify(gmsh, box, 1e-6 * F)
    if not wall:
        raise SystemExit("could not identify body surfaces")

    f = gmsh.model.mesh.field
    dist = f.add("Distance"); f.setNumbers(dist, "SurfacesList", wall)
    f.setNumber(dist, "Sampling", 60)
    grow = f.add("MathEval")
    f.setString(grow, "F", f"Min({h_far:.6g}, {h_wall:.6g} + {L['grow']}*F{dist})")
    f.setAsBackgroundMesh(grow)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", L["curv"])
    gmsh.option.setNumber("Mesh.MeshSizeMin", h_wall / 6)
    gmsh.option.setNumber("Mesh.MeshSizeMax", h_far)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)   # HXT, multithreaded
    gmsh.model.addPhysicalGroup(2, wall, name=a.wall)
    gmsh.model.addPhysicalGroup(2, far, name="farfield")
    if sym:
        gmsh.model.addPhysicalGroup(2, sym, name="symmetry")
    gmsh.model.addPhysicalGroup(3, [t for _, t in gmsh.model.getEntities(3)], name="fluid")
    gmsh.model.mesh.generate(3)
    gmsh.model.mesh.optimize("Netgen")
    gmsh.option.setNumber("Mesh.SaveAll", 0)
    gmsh.write(a.out)
    _, tags, _ = gmsh.model.mesh.getElements(3)
    n = sum(len(t) for t in tags)
    nw = sum(len(t) for s in wall for t in gmsh.model.mesh.getElements(2, s)[1])
    gmsh.finalize()
    print(f"wrote {a.out}: {n} tetrahedra, {nw} wall triangles; markers: {a.wall} "
          f"({len(wall)} surfaces), farfield ({len(far)}), symmetry ({len(sym)})")


if __name__ == "__main__":
    main()
