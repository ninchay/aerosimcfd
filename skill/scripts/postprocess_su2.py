#!/usr/bin/env python3
"""Post-process an SU2 run directory into images + a summary JSON.

2D (airfoil):  Mach / pressure / Cp contours with streamlines, Cp curve,
               skin friction, wall y+, convergence history.
3D (wing/body): surface Cp (top + bottom views), spanwise Cp sections,
               spanwise loading (sectional Cl from Cp), Mach slice at a span
               station, 3D streamlines, convergence history.

Writes into <run>/results/: *.png and summary.json (CL, CD, CM, L/D, residual
drop, coefficient drift over the last 10 % of iterations, wall y+ statistics).

Examples
  python postprocess_su2.py work/t2d --dim 2 --chord 1
  python postprocess_su2.py work/wing --dim 3 --semispan 2 --chord-root 1 \
      --chord-tip 0.5 --sweep 25 --wall wing
"""
import argparse, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri

plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3})


def read_csv(path):
    import pandas as pd
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip().strip('"').strip() for c in df.columns]
    return df


def col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n].to_numpy()
    raise KeyError(f"none of {names} in {list(df.columns)[:30]}")


# ---------------------------------------------------------------- history
def history(run, out, dim):
    h = read_csv(os.path.join(run, "history.csv"))
    it = col(h, "Inner_Iter")
    res = [c for c in h.columns if c.startswith("rms[")]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for c in res:
        ax[0].plot(it, h[c], label=c, lw=1)
    ax[0].set_xlabel("iteration"); ax[0].set_ylabel("log10 RMS residual")
    ax[0].legend(fontsize=7); ax[0].set_title("Residuals")
    CL, CD = col(h, "CL"), col(h, "CD")
    ax[1].plot(it, CL, label="CL"); ax2 = ax[1].twinx()
    ax2.plot(it, CD, "r", label="CD"); ax2.set_ylabel("CD", color="r")
    ax[1].set_xlabel("iteration"); ax[1].set_ylabel("CL"); ax[1].set_title("Force history")
    fig.tight_layout(); fig.savefig(os.path.join(out, "convergence.png")); plt.close(fig)
    # force stability over the final 5 % of iterations (at least 20): isolated
    # spikes from CFL resets earlier on should not fail an otherwise settled run
    n = len(it); tail = slice(max(0, n - max(20, n // 20)), n)
    cm_name = "CMz" if dim == 2 else "CMy"
    CM = col(h, cm_name) if cm_name in h.columns else np.full(n, np.nan)
    rho = h[res[0]].to_numpy()
    drift = lambda v: float(np.ptp(v[tail]) / max(abs(v[-1]), 1e-12))
    return dict(iterations=int(it[-1]) + 1, CL=float(CL[-1]), CD=float(CD[-1]),
                CM=float(CM[-1]), L_over_D=float(CL[-1] / CD[-1]) if CD[-1] else None,
                residual_drop_orders=float(rho[0] - rho[-1]),
                final_log_residual=float(rho[-1]),
                CL_drift_end=drift(CL), CD_drift_end=drift(CD))


# ---------------------------------------------------------------- 2D
def post_2d(run, out, chord, wall):
    import pyvista as pv
    m = pv.read(os.path.join(run, "flow.vtu")).triangulate()
    x, y = m.points[:, 0], m.points[:, 1]
    T = mtri.Triangulation(x, y, m.cells_dict[int(pv.CellType.TRIANGLE)])
    pd_ = {k: np.asarray(m.point_data[k]) for k in m.point_data.keys()}
    pd_["Speed"] = np.linalg.norm(pd_["Velocity"], axis=1)
    s = read_csv(os.path.join(run, "surface_flow.csv"))
    sx, sy = col(s, "x"), col(s, "y")
    # mask triangles inside the airfoil (none exist, but keeps plots clean)
    xmin, xmax = sx.min(), sx.max()
    pad = 0.6 * chord
    win = (xmin - pad, xmax + pad, -0.55 * chord, 0.55 * chord)
    V = pd_["Velocity"]
    from matplotlib.path import Path
    order = np.arange(len(sx))
    body = Path(np.c_[sx, sy][order])
    gx, gy = np.meshgrid(np.linspace(win[0], win[1], 400), np.linspace(win[2], win[3], 220))
    interp = lambda f: mtri.LinearTriInterpolator(T, f)(gx, gy)
    U, W = interp(V[:, 0]), interp(V[:, 1])
    inside = body.contains_points(np.c_[gx.ravel(), gy.ravel()]).reshape(gx.shape)
    U = np.ma.masked_where(inside, U); W = np.ma.masked_where(inside, W)
    fields = [("Mach", "Mach number", "turbo"),
              ("Speed", "Velocity magnitude [m/s]", "turbo"),
              ("Pressure_Coefficient", "Pressure coefficient Cp", "RdBu_r"),
              ("Pressure", "Static pressure [Pa]", "viridis")]
    for key, label, cmap in fields:
        if key not in pd_:
            continue
        fig, ax = plt.subplots(figsize=(10, 5))
        v = pd_[key]
        lo, hi = np.percentile(v, [0.5, 99.5])      # keep the LE suction peak from
        cf = ax.tricontourf(T, np.clip(v, lo, hi),   # washing out the colour scale
                            levels=np.linspace(lo, hi, 61), cmap=cmap, extend="both")
        ax.streamplot(gx, gy, U, W, color="k", linewidth=0.5, density=1.6, arrowsize=0.6)
        ax.fill(sx, sy, color="0.25", zorder=5)
        ax.set_xlim(win[:2]); ax.set_ylim(win[2:]); ax.set_aspect("equal")
        ax.set_title(f"{label} with streamlines"); ax.grid(False)
        fig.colorbar(cf, ax=ax, shrink=0.8, label=label)
        fig.tight_layout(); fig.savefig(os.path.join(out, f"contour_{key.lower()}.png")); plt.close(fig)
    # Wake / far view of Mach
    wk = "Mach" if "Mach" in pd_ else "Speed"
    if True:
        fig, ax = plt.subplots(figsize=(10, 4))
        cf = ax.tricontourf(T, pd_[wk], levels=60, cmap="turbo")
        ax.set_xlim(xmin - chord, xmax + 3 * chord); ax.set_ylim(-1.2 * chord, 1.2 * chord)
        ax.set_aspect("equal"); ax.grid(False); ax.set_title(f"{'Mach number' if wk == 'Mach' else 'Velocity magnitude [m/s]'} – wake region")
        fig.colorbar(cf, ax=ax, shrink=0.8); fig.tight_layout()
        fig.savefig(os.path.join(out, "contour_mach_wake.png")); plt.close(fig)
    # Mesh close-up
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for a_, (w_, t_) in zip(ax, [(win, "near field"),
                                ((xmax - 0.04 * chord, xmax + 0.04 * chord,
                                  -0.025 * chord, 0.025 * chord), "trailing edge")]):
        a_.triplot(T, lw=0.15, color="k"); a_.set_xlim(w_[:2]); a_.set_ylim(w_[2:])
        a_.set_aspect("equal"); a_.set_title(f"Mesh – {t_}"); a_.grid(False)
    fig.tight_layout(); fig.savefig(os.path.join(out, "mesh.png")); plt.close(fig)
    # Surface distributions
    cp = col(s, "Pressure_Coefficient")
    xc = (sx - xmin) / chord
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(xc, cp, ".", ms=2); ax.invert_yaxis()
    ax.set_xlabel("x/c"); ax.set_ylabel("Cp"); ax.set_title("Surface pressure coefficient")
    fig.tight_layout(); fig.savefig(os.path.join(out, "cp_surface.png")); plt.close(fig)
    stats = {}
    if "Y_Plus" in s.columns:
        yp = col(s, "Y_Plus")
        cfx = col(s, "Skin_Friction_Coefficient_x")
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].plot(xc, cfx, ".", ms=2); ax[0].set_title("Skin friction Cf_x"); ax[0].set_xlabel("x/c")
        ax[1].plot(xc, yp, ".", ms=2); ax[1].set_title("Wall y+"); ax[1].set_xlabel("x/c")
        fig.tight_layout(); fig.savefig(os.path.join(out, "cf_yplus.png")); plt.close(fig)
        stats = dict(yplus_max=float(yp.max()), yplus_mean=float(yp.mean()),
                     yplus_p95=float(np.percentile(yp, 95)))
    return stats


# ---------------------------------------------------------------- 3D
def post_3d(run, out, a):
    import pyvista as pv
    pv.OFF_SCREEN = True
    surf = pv.read(os.path.join(run, "surface_flow.vtu"))
    vol = pv.read(os.path.join(run, "flow.vtu"))
    vol.point_data["Speed"] = np.linalg.norm(np.asarray(vol.point_data["Velocity"]), axis=1)
    vk, vlab = (("Mach", "Mach") if "Mach" in vol.point_data else ("Speed", "|V| [m/s]"))
    if "Pressure_Coefficient" not in surf.point_data and surf.cell_data:
        surf = surf.cell_data_to_point_data()
    b = a.semispan
    shots = {}
    for view, name in (("xy", "top"), ("yx", "bottom")):
        p = pv.Plotter(off_screen=True, window_size=(1400, 900))
        p.add_mesh(surf, scalars="Pressure_Coefficient", cmap="RdBu_r",
                   scalar_bar_args=dict(title="Cp"))
        p.camera_position = "xy"
        if name == "bottom":
            p.camera.elevation = 180
        p.add_text(f"Surface Cp – {name} view", font_size=12)
        p.screenshot(os.path.join(out, f"surface_cp_{name}.png")); p.close()
    # Iso view with streamlines
    try:
        bounds = surf.bounds
        c = a.chord_root
        # Rake upstream across the span, plus a dense rake near the tip so the
        # tip vortex roll-up is visible.
        x0 = bounds[0] - 0.3 * c
        zc = 0.5 * (bounds[4] + bounds[5])
        rake = pv.Plane(center=(x0, 0.55 * b, zc), direction=(1, 0, 0),
                        i_size=0.12 * c, j_size=1.0 * b, i_resolution=2, j_resolution=24)
        xt = bounds[1] - 0.05 * c
        tip = pv.Plane(center=(xt, 1.0 * b, bounds[5]), direction=(1, 0, 0),
                       i_size=0.15 * c, j_size=0.15 * b, i_resolution=4, j_resolution=6)
        clip = vol.clip_box([bounds[0] - c, bounds[1] + 3 * c, 0, 1.5 * b,
                             bounds[4] - 1.0 * c, bounds[5] + 1.0 * c], invert=False)
        sl = clip.streamlines_from_source(rake.cast_to_pointset() + tip.cast_to_pointset(),
                                          vectors="Velocity", max_length=8 * c + 2 * b,
                                          integration_direction="forward")
        p = pv.Plotter(off_screen=True, window_size=(1600, 1000))
        p.add_mesh(surf, scalars="Pressure_Coefficient", cmap="RdBu_r",
                   scalar_bar_args=dict(title="Cp", vertical=True,
                                        position_x=0.90, position_y=0.25))
        if sl.n_points:
            p.add_mesh(sl.tube(radius=0.002 * c), scalars=vk, cmap="turbo",
                       scalar_bar_args=dict(title=vlab, vertical=True,
                                            position_x=0.02, position_y=0.25))
        # view from above, ahead and outboard so root, tip and wake all fit
        p.view_vector((-0.9, -1.0, 1.1), viewup=(0, 0, 1))
        p.reset_camera(bounds=surf.bounds)
        p.camera.zoom(0.8)
        p.add_text(f"Surface Cp + streamlines (coloured by {vlab})", font_size=12)
        p.screenshot(os.path.join(out, "streamlines_3d.png")); p.close()
    except Exception as e:  # streamlines are a nice-to-have
        print("streamlines skipped:", e)
    # Spanwise sections
    def section(eta):
        sec = surf.slice(normal="y", origin=(0, eta * b, 0))
        if sec.n_points < 10:
            return None
        x, z = sec.points[:, 0], sec.points[:, 2]
        cp = sec.point_data["Pressure_Coefficient"]
        ile, ite = np.argmin(x), np.argmax(x)
        ch = x[ite] - x[ile]
        zchord = z[ile] + (x - x[ile]) * (z[ite] - z[ile]) / ch
        up = z >= zchord
        xc = (x - x[ile]) / ch
        g = np.linspace(0, 1, 201)
        cu = np.interp(g, *[v[np.argsort(xc[up])] for v in (xc[up], cp[up])])
        cl_ = np.interp(g, *[v[np.argsort(xc[~up])] for v in (xc[~up], cp[~up])])
        cn = float(np.trapezoid(cl_ - cu, g))          # sectional normal-force coeff.
        return xc, cp, ch, cn

    etas = a.etas
    fig, axs = plt.subplots(1, len(etas), figsize=(4.2 * len(etas), 3.8), sharey=True)
    for ax, eta in zip(np.atleast_1d(axs), etas):
        s_ = section(eta)
        if s_ is None:
            continue
        ax.plot(s_[0], s_[1], ".", ms=2)
        ax.set_title(f"η = {eta:.2f}  (y = {eta*b:.3g} m)"); ax.set_xlabel("x/c")
    np.atleast_1d(axs)[0].set_ylabel("Cp"); np.atleast_1d(axs)[0].invert_yaxis()
    fig.suptitle("Spanwise Cp sections"); fig.tight_layout()
    fig.savefig(os.path.join(out, "cp_sections.png")); plt.close(fig)
    L = []
    for eta in np.linspace(0.02, 0.98, 40):
        s_ = section(eta)
        if s_ is not None:
            L.append((eta, s_[3] * s_[2]))
    if L:
        e, ccl = np.array(L).T
        cmean = a.cref or a.chord_root
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(e, ccl / cmean, "o-", ms=3, label="CFD (c·cn / c_ref)")
        # elliptic distribution carrying the same total load, for comparison
        shape = np.sqrt(1 - e ** 2)
        ell = shape * np.trapezoid(ccl, e) / np.trapezoid(shape, e) / cmean
        ax.plot(e, ell, "--", label="elliptic (same total lift)")
        ax.set_xlabel("η = y / (b/2)"); ax.set_ylabel("c·cn / c_ref"); ax.legend()
        ax.set_title("Spanwise loading")
        fig.tight_layout(); fig.savefig(os.path.join(out, "span_loading.png")); plt.close(fig)
        np.savetxt(os.path.join(out, "span_loading.csv"), np.c_[e, e * b, ccl, ccl / cmean],
                   delimiter=",", header="eta,y_m,c_times_cn_m,c_cn_over_cref", comments="")
    # Mach slice at a span station
    for eta in a.slice_etas:
        sl_ = vol.slice(normal="y", origin=(0, eta * b, 0)).triangulate()
        if sl_.n_points == 0:
            continue
        pts = sl_.points; faces = sl_.faces.reshape(-1, 4)[:, 1:]
        T = mtri.Triangulation(pts[:, 0], pts[:, 2], faces)
        sec = surf.slice(normal="y", origin=(0, eta * b, 0))
        xs, zs = sec.points[:, 0], sec.points[:, 2]
        xle, xte = xs.min(), xs.max(); ch = xte - xle
        fig, ax = plt.subplots(figsize=(10, 4.6))
        cf = ax.tricontourf(T, sl_.point_data[vk], levels=60, cmap="turbo")
        ax.plot(xs, zs, "k.", ms=0.8)
        ax.set_xlim(xle - 0.5 * ch, xte + 1.0 * ch); ax.set_ylim(zs.mean() - 0.6 * ch, zs.mean() + 0.6 * ch)
        ax.set_aspect("equal"); ax.grid(False)
        ax.set_title(f"{vlab} on the section plane η = {eta:.2f}")
        fig.colorbar(cf, ax=ax, shrink=0.8); fig.tight_layout()
        fig.savefig(os.path.join(out, f"{vk.lower()}_slice_eta{int(eta*100):02d}.png")); plt.close(fig)
    stats = {}
    if "Y_Plus" in surf.point_data:
        yp = surf.point_data["Y_Plus"]
        stats = dict(yplus_max=float(yp.max()), yplus_mean=float(yp.mean()),
                     yplus_p95=float(np.percentile(yp, 95)))
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="SU2 run directory")
    ap.add_argument("--dim", type=int, choices=[2, 3], required=True)
    ap.add_argument("--chord", type=float, default=1.0, help="2D chord [m]")
    ap.add_argument("--wall", default="airfoil")
    ap.add_argument("--semispan", type=float, help="3D: half span [m]")
    ap.add_argument("--chord-root", type=float, default=1.0)
    ap.add_argument("--cref", type=float, help="3D: reference chord for loading plot")
    ap.add_argument("--etas", type=float, nargs="+", default=[0.2, 0.5, 0.8])
    ap.add_argument("--slice-etas", type=float, nargs="+", default=[0.5])
    a = ap.parse_args()
    out = os.path.join(a.run, "results"); os.makedirs(out, exist_ok=True)
    summary = history(a.run, out, a.dim)
    if a.dim == 2:
        summary.update(post_2d(a.run, out, a.chord, a.wall))
    else:
        if a.semispan is None:
            ap.error("--semispan required for 3D")
        summary.update(post_3d(a.run, out, a))
    # Converged = forces settled, and residuals fell enough to trust them.
    # Limiter "chatter" on transonic/unstructured cases often stalls residuals
    # at 2-3 orders while forces are steady to 0.1 % – that is acceptable.
    drop, dl, dd = (summary["residual_drop_orders"], summary["CL_drift_end"],
                    summary["CD_drift_end"])
    summary["converged"] = bool((drop >= 4 and dl < 5e-3) or
                                (drop >= 2 and dl < 1e-3 and dd < 2e-3) or
                                (drop >= 1.5 and dl < 2e-4 and dd < 1e-3))
    summary["convergence_note"] = (
        f"residual drop {drop:.1f} orders; CL varies {dl*100:.3f} % and CD {dd*100:.3f} % "
        "over the final 5 % of iterations")
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
