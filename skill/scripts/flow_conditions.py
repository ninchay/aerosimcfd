#!/usr/bin/env python3
"""Freestream conditions from altitude + Mach (or speed), plus mesh sizing hints.

ISA atmosphere (0-32 km), Sutherland viscosity, Reynolds number on a reference
length, and the first-cell wall height needed for a target y+ (flat-plate
skin-friction estimate). Prints a table and writes JSON for the other scripts.

Examples
  python flow_conditions.py --alt 0 --mach 0.15 --lref 1.0 --yplus 1
  python flow_conditions.py --alt 11000 --mach 0.84 --lref 0.65 -o cond.json
  python flow_conditions.py --alt 500 --speed 35 --lref 0.25      # small UAV
"""
import argparse, json, math

R, GAMMA, G0 = 287.058, 1.4, 9.80665
# ISA layers: base altitude [m], lapse rate [K/m]
_LAYERS = [(0.0, -0.0065), (11000.0, 0.0), (20000.0, 0.001), (32000.0, None)]


def isa(h):
    """Return T [K], p [Pa], rho [kg/m^3] at geometric altitude h [m] (0-32 km)."""
    if not 0 <= h <= 32000:
        raise ValueError("altitude must be 0-32000 m for this ISA model")
    T, p = 288.15, 101325.0
    for (hb, a), (hn, _) in zip(_LAYERS[:-1], _LAYERS[1:]):
        top = min(h, hn)
        if a == 0:
            p *= math.exp(-G0 * (top - hb) / (R * T))
        else:
            Tn = T + a * (top - hb)
            p *= (Tn / T) ** (-G0 / (a * R))
            T = Tn
        if h <= hn:
            break
    return T, p, p / (R * T)


def sutherland(T):
    return 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)


def conditions(alt, lref, mach=None, speed=None, yplus=1.0, T=None):
    Ta, p, rho = isa(alt)
    if T is not None:          # temperature offset / hot day
        Ta = T
        rho = p / (R * Ta)
    a = math.sqrt(GAMMA * R * Ta)
    if mach is None:
        mach = speed / a
    V = mach * a
    mu = sutherland(Ta)
    Re = rho * V * lref / mu
    # Flat-plate turbulent skin friction (Schlichting) -> wall shear -> y1
    cf = (2 * math.log10(Re) - 0.65) ** -2.3
    utau = math.sqrt(0.5 * cf * rho * V ** 2 / rho)
    y1 = yplus * mu / (rho * utau)
    # Boundary-layer thickness estimate at the trailing edge (turbulent)
    delta = 0.37 * lref / Re ** 0.2
    regime = ("incompressible (M<0.3)" if mach < 0.3 else
              "subsonic compressible" if mach < 0.75 else
              "transonic" if mach < 1.2 else "supersonic")
    return dict(altitude_m=alt, mach=mach, speed_mps=V, T_K=Ta, p_Pa=p,
                rho=rho, a_mps=a, mu=mu, nu=mu / rho, q_Pa=0.5 * rho * V ** 2,
                lref_m=lref, reynolds=Re, target_yplus=yplus,
                first_cell_height_m=y1, bl_thickness_m=delta, regime=regime)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alt", type=float, default=0.0, help="altitude [m]")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mach", type=float)
    g.add_argument("--speed", type=float, help="true airspeed [m/s]")
    ap.add_argument("--lref", type=float, required=True,
                    help="reference length for Re, usually mean chord [m]")
    ap.add_argument("--yplus", type=float, default=1.0,
                    help="target y+ (1 for resolved wall, 30-100 for wall functions)")
    ap.add_argument("--T", type=float, help="override static temperature [K]")
    ap.add_argument("-o", "--out", help="write JSON here")
    a = ap.parse_args()
    c = conditions(a.alt, a.lref, a.mach, a.speed, a.yplus, a.T)
    for k, v in c.items():
        print(f"{k:22s} {v:.6g}" if isinstance(v, float) else f"{k:22s} {v}")
    if a.out:
        json.dump(c, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
