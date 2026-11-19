"""Pipe case driver: inlet M = 0.5 (ISA sea level static state at the inlet).

Inlet = total conditions (p0, T0 of the M 0.5 state); outlet = static pressure.
The outlet pressure is adjusted until the area-averaged inlet Mach number is 0.5
(the friction pressure drop sets it), restarting from the previous solution.
"""
import argparse, csv, os, shutil, subprocess
ap = argparse.ArgumentParser()
ap.add_argument("--L", type=float, default=2.2); ap.add_argument("--D", type=float, default=0.5)
ap.add_argument("--mach", type=float, default=0.5)
ap.add_argument("--p", type=float, default=101325.0); ap.add_argument("--T", type=float, default=288.15)
ap.add_argument("--p_out", type=float, default=95400.0)
ap.add_argument("--iters", type=int, default=4000); ap.add_argument("--rounds", type=int, default=4)
ap.add_argument("--tol", type=float, default=0.002)
a = ap.parse_args()
g = 1.4
T0 = a.T * (1 + 0.5 * (g - 1) * a.mach ** 2)
p0 = a.p * (1 + 0.5 * (g - 1) * a.mach ** 2) ** (g / (g - 1))
tmpl = open("pipe_template.cfg").read()
p_out = a.p_out

def inlet_mach():
    rows = list(csv.DictReader(open("history.csv")))
    last = {k.strip().strip('"'): v for k, v in rows[-1].items()}
    return float(last["Avg_Mach(inlet)"]) if "Avg_Mach(inlet)" in last else None, last

for f in ("restart_flow.dat", "history.csv"):
    if os.path.exists(f):
        os.remove(f)
# warm-up: first-order upwind from the uniform inlet state, then second order
for k in range(-1, a.rounds):
    restart = "YES" if os.path.exists("restart_flow.dat") else "NO"
    muscl = "NO" if k < 0 else "YES"
    open("pipe.cfg", "w").write(tmpl.format(restart=restart, mach=a.mach, p_static=a.p, t_static=a.T,
                                           D=a.D, t_total=f"{T0:.3f}", p_total=f"{p0:.2f}",
                                           p_out=f"{p_out:.2f}", muscl=muscl,
                                           iters=1500 if k < 0 else a.iters))
    print(f"round {k}: p0 {p0:.1f} Pa, T0 {T0:.2f} K, p_out {p_out:.1f} Pa, restart {restart}", flush=True)
    subprocess.run(["SU2_CFD", "pipe.cfg"], check=True, stdout=open(f"su2_round{k}.log", "w"))
    M_in, _ = inlet_mach()
    print(f"   inlet Mach {M_in:.4f}", flush=True)
    if k < 0:
        shutil.copy("restart_flow.dat", "restart_warmup.dat")   # kept in case a round fails
        continue
    if abs(M_in - a.mach) < a.tol * a.mach:
        break
    # inlet Mach is set by p0/p_in; move p_out by the same amount the inlet pressure must move
    p_in_now = p0 / (1 + 0.2 * M_in ** 2) ** 3.5
    p_out += (a.p - p_in_now)
print(f"final p_out = {p_out:.1f} Pa")
