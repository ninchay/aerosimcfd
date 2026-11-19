"""Structured axisymmetric mesh of a straight pipe for SU2 (x = axis, y = radius).

Markers: inlet (x=0), outlet (x=L), wall (y=R), axis (y=0).
"""
import argparse, math
import gmsh

ap = argparse.ArgumentParser()
ap.add_argument("--L", type=float, default=2.2)
ap.add_argument("--D", type=float, default=0.5)
ap.add_argument("--y1", type=float, default=2e-6, help="first cell height at the wall [m]")
ap.add_argument("--nr", type=int, default=90, help="cells across the radius")
ap.add_argument("--nx", type=int, default=220, help="cells along the pipe")
ap.add_argument("-o", default="pipe.su2")
a = ap.parse_args()
R = a.D / 2

# geometric growth ratio r so that y1 * (r^n - 1)/(r - 1) = R
lo, hi = 1.0 + 1e-9, 2.0
for _ in range(200):
    r = 0.5 * (lo + hi)
    s = a.y1 * (r ** a.nr - 1) / (r - 1)
    lo, hi = (r, hi) if s < R else (lo, r)
print(f"radial growth ratio {r:.4f}, last cell {a.y1 * r ** (a.nr - 1) * 1e3:.2f} mm")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("pipe")
geo = gmsh.model.geo
p1 = geo.addPoint(0, 0, 0); p2 = geo.addPoint(a.L, 0, 0)
p3 = geo.addPoint(a.L, R, 0); p4 = geo.addPoint(0, R, 0)
axis = geo.addLine(p1, p2); outlet = geo.addLine(p2, p3)
wall = geo.addLine(p3, p4); inlet = geo.addLine(p4, p1)
loop = geo.addCurveLoop([axis, outlet, wall, inlet])
surf = geo.addPlaneSurface([loop])
geo.synchronize()
# gmsh "Progression" r > 1 grows the cells along the curve direction; -r reverses it.
# outlet runs axis->wall (smallest cell must be at its end), inlet runs wall->axis (at its start)
gmsh.model.mesh.setTransfiniteCurve(outlet, a.nr + 1, "Progression", -r)
gmsh.model.mesh.setTransfiniteCurve(inlet, a.nr + 1, "Progression", r)
# mild streamwise clustering toward the inlet, where the boundary layer starts
gmsh.model.mesh.setTransfiniteCurve(axis, a.nx + 1, "Progression", 1.01)
gmsh.model.mesh.setTransfiniteCurve(wall, a.nx + 1, "Progression", -1.01)
gmsh.model.mesh.setTransfiniteSurface(surf)
gmsh.model.mesh.setRecombine(2, surf)
for name, tag in (("inlet", inlet), ("outlet", outlet), ("wall", wall), ("axis", axis)):
    gmsh.model.setPhysicalName(1, gmsh.model.addPhysicalGroup(1, [tag]), name)
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [surf]), "fluid")
gmsh.model.mesh.generate(2)
gmsh.write(a.o)
gmsh.finalize()
