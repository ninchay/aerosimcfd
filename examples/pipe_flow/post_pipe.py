"""Plots and tables for the axisymmetric pipe run (reads SU2's flow.vtu / surface_flow.csv)."""
import json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyvista as pv

out = "results"; os.makedirs(out, exist_ok=True)
m = pv.read("flow.vtu")
P = m.points[:, :2]
f = {k: np.asarray(m.point_data[k]) for k in m.point_data.keys()}
f["U"] = f["Velocity"][:, 0]; f["Vr"] = f["Velocity"][:, 1]
f["Speed"] = np.linalg.norm(f["Velocity"][:, :2], axis=1)

# structured grid: columns of equal x, rows of increasing r
xs = np.unique(np.round(P[:, 0], 9)); nx = len(xs); nr = len(P) // nx
order = np.lexsort((P[:, 1], np.round(P[:, 0], 9)))
X = P[order, 0].reshape(nx, nr); Y = P[order, 1].reshape(nx, nr)
G = {k: (v[order].reshape(nx, nr) if v.ndim == 1 else None) for k, v in f.items()}
R, L = Y.max(), X.max()

def area_avg(F):          # ∫ F 2πr dr / πR²
    return np.trapezoid(F * Y, Y, axis=1) * 2 / R ** 2

def mass_avg(F):          # ∫ ρu F r dr / ∫ ρu r dr
    w = G["Density"] * G["U"] * Y
    return np.trapezoid(w * F, Y, axis=1) / np.trapezoid(w, Y, axis=1)

x = X[:, 0]
prof = dict(x=x,
            p_area=area_avg(G["Pressure"]), p_axis=G["Pressure"][:, 0],
            U_bulk=np.trapezoid(G["Density"] * G["U"] * Y, Y, axis=1) / np.trapezoid(G["Density"] * Y, Y, axis=1),
            U_axis=G["U"][:, 0], M_mass=mass_avg(G["Mach"]), M_axis=G["Mach"][:, 0],
            T_mass=mass_avg(G["Temperature"]), rho_area=area_avg(G["Density"]),
            mdot=np.trapezoid(G["Density"] * G["U"] * 2 * np.pi * Y, Y, axis=1))
np.savetxt(os.path.join(out, "axial_profiles.csv"), np.c_[tuple(prof.values())], delimiter=",",
           header=",".join(prof.keys()), comments="", fmt="%.6g")

# ---- contours (mirror about the axis to show the whole pipe)
def contour(key, label, fname, cmap="turbo", scale=1.0):
    Z = G[key] * scale
    fig, ax = plt.subplots(figsize=(13, 3.9))
    lv = np.linspace(Z.min(), Z.max(), 61)
    for s in (1, -1):
        cf = ax.contourf(X, s * Y, Z, levels=lv, cmap=cmap)
    ax.plot([0, L], [R, R], "k", lw=2); ax.plot([0, L], [-R, -R], "k", lw=2)
    ax.plot([0, L], [0, 0], "k-.", lw=0.6, alpha=0.5)
    ax.annotate("INLET\nM 0.5", (0, 0), (-0.13, 0), ha="center", va="center", fontsize=9)
    ax.annotate("OUTLET", (L, 0), (L + 0.12, 0), ha="center", va="center", fontsize=9)
    ax.set_aspect("equal"); ax.set_xlim(-0.25, L + 0.25)
    ax.set_xlabel("x  [m]  (flow →)"); ax.set_ylabel("r  [m]")
    ax.set_title(f"{label} — pipe L = {L:.1f} m, D = {2*R:.1f} m, inlet M 0.5 (axisymmetric RANS-SA)")
    fig.colorbar(cf, ax=ax, label=label, pad=0.01, fraction=0.03)
    fig.tight_layout(); fig.savefig(os.path.join(out, fname), dpi=150); plt.close(fig)

contour("Pressure", "Static pressure [kPa]", "contour_pressure.png", "viridis", 1e-3)
contour("Speed", "Velocity magnitude [m/s]", "contour_velocity.png")
contour("Mach", "Mach number", "contour_mach.png")

# ---- inlet -> outlet line plots
fig, ax = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
ax[0].plot(x, prof["p_area"] / 1e3, lw=2, label="area-averaged")
ax[0].plot(x, prof["p_axis"] / 1e3, "--", label="centreline")
ax[0].set_ylabel("Static pressure [kPa]"); ax[0].legend()
ax[1].plot(x, prof["U_bulk"], lw=2, label="bulk (mass-flux / ρ̄A)")
ax[1].plot(x, prof["U_axis"], "--", label="centreline")
ax[1].set_ylabel("Axial velocity [m/s]"); ax[1].legend()
ax[2].plot(x, prof["M_mass"], lw=2, label="mass-averaged")
ax[2].plot(x, prof["M_axis"], "--", label="centreline")
ax[2].set_ylabel("Mach number"); ax[2].set_xlabel("x [m]  (inlet → outlet)"); ax[2].legend()
for a in ax: a.grid(alpha=0.3)
fig.suptitle("Pressure, velocity and Mach from inlet to outlet")
fig.tight_layout(); fig.savefig(os.path.join(out, "inlet_to_outlet.png"), dpi=150); plt.close(fig)

# ---- radial velocity profiles at stations
fig, ax = plt.subplots(figsize=(7, 5))
for xi in (0.0, 0.25, 0.55, 1.1, 1.65, 2.2):
    i = np.argmin(abs(x - xi))
    ax.plot(G["U"][i], Y[i] / R, label=f"x = {x[i]:.2f} m")
ax.set_xlabel("Axial velocity u [m/s]"); ax.set_ylabel("r / R  (0 = axis, 1 = wall)")
ax.set_title("Velocity profiles developing along the pipe"); ax.legend(); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(os.path.join(out, "velocity_profiles.png"), dpi=150); plt.close(fig)

# ---- summary
yp = None
if os.path.exists("surface_flow.csv"):
    import csv
    rows = list(csv.DictReader(open("surface_flow.csv")))
    k = next((c for c in rows[0] if "Y_Plus" in c), None)
    if k:
        yp = np.array([float(r[k]) for r in rows])
summary = {}
for name, i in (("inlet", 0), ("outlet", -1)):
    summary[name] = dict(x_m=float(x[i]), p_static_Pa=float(prof["p_area"][i]),
                         p_centreline_Pa=float(prof["p_axis"][i]), U_bulk_m_s=float(prof["U_bulk"][i]),
                         U_centreline_m_s=float(prof["U_axis"][i]), Mach_mass_avg=float(prof["M_mass"][i]),
                         Mach_centreline=float(prof["M_axis"][i]), T_K=float(prof["T_mass"][i]),
                         rho_kg_m3=float(prof["rho_area"][i]), mdot_kg_s=float(prof["mdot"][i]))
summary["pressure_drop_Pa"] = summary["inlet"]["p_static_Pa"] - summary["outlet"]["p_static_Pa"]
summary["mass_imbalance_pct"] = 100 * (summary["outlet"]["mdot_kg_s"] / summary["inlet"]["mdot_kg_s"] - 1)
if yp is not None:
    summary["wall_yplus"] = dict(max=float(yp.max()), mean=float(yp.mean()))
json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=2)
print(json.dumps(summary, indent=2))
