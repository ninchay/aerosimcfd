#!/usr/bin/env python3
"""Generate test geometry: a NACA 4-digit airfoil (.dat) and/or a tapered, swept
half-wing as a STEP solid. Useful for validating the pipeline when the user has
no CAD yet, and as a template for parametric studies.

Coordinates: x streamwise (LE of root at origin), y spanwise (root at y=0,
so the y=0 plane can be a symmetry plane), z up. Units: metres.

Examples
  python make_naca_wing.py --naca 0012 --chord 1 --dat naca0012.dat
  python make_naca_wing.py --naca 2412 --chord 0.8 --taper 0.5 --semispan 2.0 \
      --sweep 25 --dihedral 3 --twist -2 --step wing.step
"""
import argparse, math
import numpy as np


def naca4(code, n=161, closed_te=True):
    """Return (n_points, 2) array, TE -> upper -> LE -> lower -> TE (Selig order)."""
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    beta = np.linspace(0, math.pi, n)
    x = 0.5 * (1 - np.cos(beta))                      # cosine spacing
    a4 = -0.1036 if closed_te else -0.1015
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2
                  + 0.2843 * x**3 + a4 * x**4)
    if m == 0 or p == 0:
        yc = np.zeros_like(x); dyc = np.zeros_like(x)
    else:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2),
                      m / (1 - p)**2 * ((1 - 2 * p) + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p)**2 * (p - x))
    th = np.arctan(dyc)
    xu, yu = x - yt * np.sin(th), yc + yt * np.cos(th)
    xl, yl = x + yt * np.sin(th), yc - yt * np.cos(th)
    up = np.c_[xu[::-1], yu[::-1]]
    lo = np.c_[xl[1:], yl[1:]]
    return np.vstack([up, lo])


def write_dat(path, xy, name):
    with open(path, "w") as f:
        f.write(f"{name}\n")
        for x, y in xy:
            f.write(f"{x:.7f} {y:.7f}\n")


def make_wing_step(path, code, chord, taper, semispan, sweep, dihedral, twist,
                   n=121):
    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("wing")
    occ = gmsh.model.occ
    xy = naca4(code, n)[:-1]          # drop duplicated TE point; spline closes it
    wires = []
    for eta in (0.0, 1.0):
        c = chord * (1 - eta * (1 - taper))
        y = eta * semispan
        xle = y * math.tan(math.radians(sweep))
        zle = y * math.tan(math.radians(dihedral))
        tw = math.radians(eta * twist)     # linear twist, about the local LE
        pts = []
        for px, pz in xy:
            X, Z = px * c, pz * c
            Xr = X * math.cos(tw) + Z * math.sin(tw)
            Zr = -X * math.sin(tw) + Z * math.cos(tw)
            pts.append(occ.addPoint(xle + Xr, y, zle + Zr))
        # Two splines meeting at the sharp TE and at the LE keep the TE edge crisp
        ile = int(np.argmin(xy[:, 0]))
        s1 = occ.addSpline(pts[:ile + 1])
        s2 = occ.addSpline(pts[ile:] + [pts[0]])
        wires.append(occ.addWire([s1, s2]))
    occ.addThruSections(wires, makeSolid=True, makeRuled=True)
    occ.synchronize()
    gmsh.write(path)
    gmsh.finalize()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--naca", default="0012")
    ap.add_argument("--chord", type=float, default=1.0, help="root chord [m]")
    ap.add_argument("--taper", type=float, default=1.0, help="tip/root chord")
    ap.add_argument("--semispan", type=float, default=2.0, help="[m]")
    ap.add_argument("--sweep", type=float, default=0.0, help="LE sweep [deg]")
    ap.add_argument("--dihedral", type=float, default=0.0, help="[deg]")
    ap.add_argument("--twist", type=float, default=0.0, help="tip twist, -ve = washout [deg]")
    ap.add_argument("--dat", help="write airfoil coordinates (unit chord x chord) here")
    ap.add_argument("--step", help="write half-wing STEP solid here")
    a = ap.parse_args()
    if a.dat:
        write_dat(a.dat, naca4(a.naca) * a.chord, f"NACA {a.naca}")
    if a.step:
        make_wing_step(a.step, a.naca, a.chord, a.taper, a.semispan, a.sweep,
                       a.dihedral, a.twist)
        S = a.semispan * a.chord * (1 + a.taper) / 2
        lam = a.taper
        mac = 2 / 3 * a.chord * (1 + lam + lam**2) / (1 + lam)
        print(f"half-wing area S/2 = {S:.4f} m^2, MAC = {mac:.4f} m, "
              f"AR = {(2 * a.semispan)**2 / (2 * S):.2f}")
    if not (a.dat or a.step):
        ap.error("give --dat and/or --step")


if __name__ == "__main__":
    main()
