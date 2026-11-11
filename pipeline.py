"""Case model and solver pipeline for AeroSim Workbench.

Every step calls the aircraft-cfd-fea skill scripts exactly as the skill
describes (Gmsh -> SU2 -> CalculiX), records the command in commands.sh so the
case can be rerun outside the app, and stores what the UI needs in state.json.
"""
import copy, glob, hashlib, json, math, os, re, shlex, shutil, signal, subprocess, sys, threading, time

import numpy as np

import preview

APP = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(APP, "skill", "scripts")
WORK = os.environ.get("AEROSIM_WORK", os.path.join(APP, "work"))
sys.path.insert(0, SCRIPTS)
from flow_conditions import conditions as _flow_conditions  # noqa: E402

STEPS = ["geometry", "conditions", "mesh", "setup", "solve", "results", "polar", "structure", "report", "handoff"]
LABEL = dict(geometry="Geometry", conditions="Flow Conditions", mesh="Mesh", setup="Setup",
             solve="Solution", results="Results", polar="Polar Sweep", structure="Static Structural",
             report="Report", handoff="Handoff Package")
# which settings section invalidates which first step
SECTION_STEP = dict(geometry="geometry", conditions="conditions", references="setup",
                    mesh="mesh", solver="setup", structure="structure")
MATERIALS = ["Al7075-T6", "Al2024-T3", "Al6061-T6", "Ti-6Al-4V", "Steel-4130",
             "CFRP-quasi-iso", "GFRP-quasi-iso", "PLA-print"]

DEFAULTS = dict(
    geometry=dict(source="naca_wing", naca="2412", chord=1.0, taper=0.5, semispan=2.0,
                  sweep=10.0, dihedral=0.0, twist=0.0, cad_file="", units="auto", half="auto"),
    conditions=dict(alt=0.0, spec="mach", mach=0.3, speed=50.0, aoa=4.0, beta=0.0, T_override=None, polar=""),
    references=dict(lref=None, sref=None, xmom=None),
    mesh=dict(level="auto", y1=None, wall_h=None, farfield=None, max_cells=1.5e6),
    solver=dict(solver="auto", turb="SA", wall_functions="auto", iterations=None,
                resmin=None, cfl=None, cfl_max=None, threads=None),
    structure=dict(enabled=True, model="shell", thickness=0.0015, material="Al7075-T6",
                   load_factor=1.5, h=None, clamp_axis="y", clamp_value=None,
                   E=None, nu=None, allowable=None),
)

_jobs = {}            # case id -> Job
_lock = threading.Lock()


# ===================================================================== helpers
def case_dir(cid):
    d = os.path.realpath(os.path.join(WORK, cid))
    if not d.startswith(os.path.realpath(WORK) + os.sep) or not os.path.isdir(d):
        raise KeyError(cid)
    return d


def jload(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=float)
    os.replace(tmp, p)


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def _hash(obj):
    return hashlib.md5(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:10]


def num(v, d=None):
    if v in (None, "", "auto"):
        return d
    return float(v)


# ===================================================================== cases
def list_cases():
    os.makedirs(WORK, exist_ok=True)
    out = []
    for d in sorted(glob.glob(os.path.join(WORK, "*", "case.json")), key=os.path.getmtime, reverse=True):
        c = jload(d, {})
        out.append(dict(id=os.path.basename(os.path.dirname(d)), name=c.get("name", "?"),
                        created=c.get("created"), dim=derive(c).get("dim") if c else None))
    return out


def create_case(name, template=None):
    os.makedirs(WORK, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:40] or "case"
    cid = f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}"
    d = os.path.join(WORK, cid)
    os.makedirs(d)
    settings = copy.deepcopy(DEFAULTS)
    if template == "airfoil":
        settings["geometry"].update(source="naca2d", naca="0012", chord=1.0)
        settings["conditions"].update(mach=0.15, aoa=10.0)
    settings = dict(name=name, created=time.strftime("%Y-%m-%d %H:%M"), **settings)
    jsave(os.path.join(d, "case.json"), settings)
    jsave(os.path.join(d, "state.json"), dict(steps={}, hashes={}))
    write_commands(d, {})
    return cid


def delete_case(cid):
    d = case_dir(cid)
    if cid in _jobs and _jobs[cid].alive():
        raise RuntimeError("stop the running job first")
    shutil.rmtree(d)


def load(cid):
    d = case_dir(cid)
    c = jload(os.path.join(d, "case.json"), {})
    return d, merge(dict(DEFAULTS, name=c.get("name", cid)), c)


def save_settings(cid, new):
    d, c = load(cid)
    st = jload(os.path.join(d, "state.json"), dict(steps={}, hashes={}))
    old = copy.deepcopy(c)
    for sec in DEFAULTS:
        if sec in new:
            c[sec] = merge(c[sec], new[sec])
    if "name" in new:
        c["name"] = str(new["name"])[:80]
    jsave(os.path.join(d, "case.json"), c)
    # mark everything from the first affected step onward as needing update
    first = None
    strip = lambda x: {k: v for k, v in (x or {}).items() if k != "polar"}
    if str(old["conditions"].get("polar")) != str(c["conditions"].get("polar")):
        first = STEPS.index("polar")       # the α list only affects the sweep
    for sec, step in SECTION_STEP.items():
        if _hash(strip(old.get(sec))) != _hash(strip(c.get(sec))):
            i = STEPS.index(step)
            first = i if first is None else min(first, i)
    # changing CAD or 2D/3D also changes the conditions (lref) etc.
    if first is not None:
        affected = STEPS[first:]
        if STEPS[first] == "polar":              # only the α list changed
            affected = ["polar", "report", "handoff"]
        for s in affected:
            if st["steps"].get(s, {}).get("status") in ("ok", "skipped"):
                st["steps"][s]["status"] = "stale"
        jsave(os.path.join(d, "state.json"), st)
    return c


def save_upload(cid, filename, data):
    d, c = load(cid)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".step", ".stp", ".iges", ".igs", ".brep", ".stl", ".dat", ".txt"):
        raise ValueError("supported: STEP, IGES, BREP, STL (3D) or .dat airfoil (2D)")
    os.makedirs(os.path.join(d, "geom"), exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(filename))
    p = os.path.join(d, "geom", "upload_" + safe)
    with open(p, "wb") as f:
        f.write(data)
    src = "dat2d" if ext in (".dat", ".txt") else "cad"
    save_settings(cid, dict(geometry=dict(source=src, cad_file=os.path.relpath(p, d))))
    return os.path.relpath(p, d)


# ===================================================================== derived set-up
def derive(c, d=None):
    """Everything the skill decides from the user's inputs, with the reasons."""
    g, fc, r, ms, sv, stc = (c.get(k, DEFAULTS[k]) for k in
                             ("geometry", "conditions", "references", "mesh", "solver", "structure"))
    g = merge(DEFAULTS["geometry"], g); fc = merge(DEFAULTS["conditions"], fc)
    r = merge(DEFAULTS["references"], r); ms = merge(DEFAULTS["mesh"], ms)
    sv = merge(DEFAULTS["solver"], sv); stc = merge(DEFAULTS["structure"], stc)
    notes = []
    src = g["source"]
    dim = 2 if src in ("naca2d", "dat2d") else 3
    out = dict(dim=dim, source=src, notes=notes)
    gi = (jload(os.path.join(d, "geom", "geom_info.json")) if d else None) or {}
    chord = num(g["chord"], 1.0)

    if dim == 2:
        lref, sref, xmom = chord, chord, 0.25 * chord
        out.update(chord=chord, half=False, scale=1.0, wall="airfoil")
        notes.append("2D: reference area = chord (unit span), moment about 25 % chord.")
    elif src == "naca_wing":
        lam, b = num(g["taper"], 1.0), num(g["semispan"], 1.0)
        sw = math.radians(num(g["sweep"], 0.0))
        S = b * chord * (1 + lam) / 2
        mac = 2 / 3 * chord * (1 + lam + lam ** 2) / (1 + lam)
        y_mac = b * (1 + 2 * lam) / (3 * (1 + lam))
        lref, sref, xmom = mac, S, y_mac * math.tan(sw) + 0.25 * mac
        AR = (2 * b) ** 2 / (2 * S)
        out.update(chord=chord, chord_root=chord, semispan=b, half=True, scale=1.0, wall="wing",
                   aspect_ratio=AR, mac=mac, sweep_le=math.degrees(sw), taper=lam,
                   step=True)
        notes.append(f"Half-wing with symmetry plane at y = 0: S_ref = {S:.4g} m² (half), "
                     f"c_ref = MAC = {mac:.4g} m, moment at 25 % MAC (x = {xmom:.4g} m). Forces are for the half.")
    else:
        ext = os.path.splitext(g.get("cad_file") or "")[1].lower()
        units = g.get("units", "auto")
        scale = 0.001 if units == "mm" else 1.0 if units == "m" else gi.get("scale_guess", 1.0)
        if units == "auto" and gi:
            notes.append(f"CAD units assumed {'mm' if scale == 0.001 else 'm'} "
                         f"(largest dimension {gi.get('size', 0):.4g} units).")
        stl = ext == ".stl"
        half = (g.get("half") == "yes") or (g.get("half") == "auto" and gi.get("cut_on_y0") and not stl)
        if stl and half:
            half = False; notes.append("STL input: full-body model (half models need STEP).")
        L = gi.get("x_length", 1.0) * scale
        S = gi.get("projected_area", 1.0) * scale ** 2
        bb = gi.get("bbox", [0, 0, 0, 1, 1, 1])
        lref, sref = L, S
        xmom = bb[0] * scale + 0.25 * L
        semispan = (bb[4] - max(bb[1], 0 if half else bb[1])) * scale
        if not half:
            semispan = (bb[4] - bb[1]) * scale / 2
        out.update(chord=L, chord_root=L, semispan=semispan, half=bool(half), scale=scale,
                   wall="body", step=not stl and bool(g.get("cad_file")),
                   aspect_ratio=(2 * semispan) ** 2 / (S * (2 if half else 1)) if S else None)
        if gi:
            notes.append(f"References from the CAD: c_ref = x-length {L:.4g} m, S_ref = projected "
                         f"area {S:.4g} m²{' (half model)' if half else ''}; override under References.")
    lref = num(r["lref"], lref); sref = num(r["sref"], sref); xmom = num(r["xmom"], xmom)
    out.update(lref=lref, sref=sref, xmom=xmom)

    # flow conditions (quick, for decisions; the conditions step writes cond.json)
    try:
        kw = dict(mach=num(fc["mach"])) if fc["spec"] == "mach" else dict(speed=num(fc["speed"]))
        cond = _flow_conditions(num(fc["alt"], 0.0), lref, yplus=1.0, T=num(fc.get("T_override")), **kw)
        M = cond["mach"]
    except Exception as e:  # noqa
        cond, M = None, None
        notes.append(f"Flow conditions invalid: {e}")
    out["mach"] = M

    # solver choice (skill §2)
    choice = sv["solver"]
    inc = M is not None and M < 0.1
    if choice == "auto":
        if dim == 2:
            solver = "INC_RANS" if inc else "RANS"
            notes.append("2D airfoil: RANS with a resolved wall (y+ ≈ 1).")
        else:
            solver = "INC_EULER" if inc else "EULER"
            notes.append("3D tetra mesh cannot resolve the wall: Euler for pressure, lift, moments and loads "
                         "(choose RANS for viscous effects).")
        if inc:
            notes.append("M < 0.1: incompressible solver (the compressible one is stiff here).")
    else:
        solver = choice
    viscous = solver in ("RANS", "INC_RANS")
    turb = sv["turb"]
    wf = False
    if viscous and dim == 3:
        wf = sv["wall_functions"] in ("auto", True, "yes")
        if wf:
            notes.append("3D RANS on tetrahedra: wall functions; keep y+ ≤ ~150 if lift matters.")
        if turb == "SST":
            notes.append("Warning: SST on coarse 3D tet meshes failed to converge in testing; SA is recommended.")
    yplus = 1.0 if dim == 2 else 50.0
    out.update(solver=solver, viscous=viscous, turb=turb, wall_functions=wf, target_yplus=yplus)
    if cond:
        cond_y = _flow_conditions(num(fc["alt"], 0.0), lref, yplus=yplus, T=num(fc.get("T_override")), **kw)
        out["cond"] = cond_y
        out["regime"] = cond_y["regime"]
    if dim == 3 and solver in ("EULER", "INC_EULER"):
        notes.append("Trust: pressure, CL, moments and loads usable; 3D drag on coarse tets is not "
                     "(numerical dissipation) — quote CD only with a mesh study.")
    out["level"] = ms["level"] if ms["level"] != "auto" else ("medium" if dim == 2 else "coarse")
    out["iterations"] = int(num(sv["iterations"], 5000 if dim == 2 else (2000 if viscous else 1500)))
    out["threads"] = int(num(sv["threads"], os.cpu_count() or 1))
    out["structure"] = bool(stc["enabled"]) and dim == 3 and out.get("step", False)
    if dim == 3 and stc["enabled"] and not out.get("step"):
        notes.append("Structure needs a STEP/IGES solid (or the parametric wing); skipped for STL.")
    return out


# ===================================================================== hand estimates (skill §6.3)
def _camber_alpha0(dat):
    """Zero-lift angle [deg] from the mean line of a Selig-order airfoil (thin-airfoil theory)."""
    P = _read_dat(dat)
    i = int(np.argmin(P[:, 0]))
    up, lo = P[:i + 1][::-1], P[i:]
    c0, c1 = P[:, 0].min(), P[:, 0].max()
    x = c0 + (c1 - c0) * 0.5 * (1 - np.cos(np.linspace(0, np.pi, 200)))
    zu = np.interp(x, up[:, 0], up[:, 1]); zl = np.interp(x, lo[:, 0], lo[:, 1])
    zc = (zu + zl) / 2 / (c1 - c0)
    xs = (x - c0) / (c1 - c0)
    th = np.arccos(1 - 2 * xs)
    dz = np.gradient(zc, xs)
    f = dz * (np.cos(th) - 1)
    a0 = -np.trapezoid(f, th) / np.pi if hasattr(np, "trapezoid") else -np.trapz(f, th) / np.pi
    return math.degrees(a0)


def _read_dat(p):
    pts = []
    for line in open(p):
        v = line.replace(",", " ").split()
        try:
            if len(v) >= 2:
                pts.append([float(v[0]), float(v[1])])
        except ValueError:
            continue
    return np.array(pts)


def estimate(c, dv, d):
    aoa = num(c["conditions"]["aoa"], 0.0)
    M = dv.get("mach") or 0.0
    beta = math.sqrt(max(1 - M ** 2, 0.05))
    dat = os.path.join(d, "geom", "foil.dat")
    a0, src = 0.0, "symmetric section assumed (α₀ = 0)"
    if os.path.exists(dat):
        try:
            a0 = _camber_alpha0(dat); src = f"thin-airfoil α₀ = {a0:.2f}° from the section camber"
        except Exception:
            pass
    if M >= 0.8:
        return dict(method="none", note="Prandtl–Glauert not valid at M ≥ 0.8; compare with test data instead.")
    if dv["dim"] == 2:
        CL = 2 * math.pi * math.radians(aoa - a0) / beta
        return dict(method="thin airfoil + Prandtl–Glauert", CL=CL, note=src +
                    "; inviscid, so viscous RANS lift is typically 5–10 % lower.")
    AR = dv.get("aspect_ratio") or 6.0
    sw = math.radians(dv.get("sweep_le") or 0.0)
    lam = dv.get("taper") or 1.0
    # sweep at half chord from the LE sweep
    b = dv.get("semispan") or 1.0; cr = dv.get("chord_root") or 1.0
    tan_c2 = math.tan(sw) - 0.5 * cr * (1 - lam) / b if dv["source"] == "naca_wing" else math.tan(sw)
    CLa = 2 * math.pi * AR / (2 + math.sqrt(AR ** 2 * beta ** 2 / 0.95 ** 2 * (1 + tan_c2 ** 2 / beta ** 2) + 4))
    twist = num(c["geometry"].get("twist"), 0.0) if dv["source"] == "naca_wing" else 0.0
    a_eff = aoa - a0 + 0.4 * twist          # rough: linear twist, elliptic-ish loading
    return dict(method="lifting-line (Helmbold/DATCOM) + Prandtl–Glauert", CL=CLa * math.radians(a_eff),
                CLalpha_per_rad=CLa, AR=AR,
                note=src + f"; AR = {AR:.2f}" + (f", twist {twist}° approximated" if twist else ""))


# ===================================================================== job runner
class Job:
    def __init__(self, cid, steps):
        self.cid, self.steps = cid, steps
        self.proc, self.cancel, self.current = None, False, None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def alive(self):
        return self.thread.is_alive()

    def stop(self):
        self.cancel = True
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except Exception:
                self.proc.terminate()

    # ---- shell
    def sh(self, d, args, cwd=None, log_name="log.txt", record=True, display=None):
        """Run a command, stream its output to the case log, record it in commands.sh."""
        env = dict(os.environ)
        su2 = os.environ.get("SU2_RUN") or os.path.expanduser("~/tools/su2/bin")
        env["PATH"] = su2 + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = su2 + os.pathsep + env.get("PYTHONPATH", "")
        env["MPLBACKEND"] = "Agg"
        env.setdefault("PYVISTA_OFF_SCREEN", "true")
        cwd = cwd or d
        rel = os.path.relpath(cwd, d)
        line = " ".join(shlex.quote(a) for a in args).replace(SCRIPTS, "$SKILL").replace(sys.executable, "python3")
        if record:
            self.cmds.append(f"(cd {rel} && {line})" if rel != "." else line)
        log = open(os.path.join(d, log_name), "a")
        log.write(f"\n$ {display or line}\n"); log.flush()
        self.proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     start_new_session=True)
        tail = []
        for ln in self.proc.stdout:
            log.write(ln); log.flush()
            tail.append(ln); tail = tail[-60:]
        rc = self.proc.wait()
        log.close()
        if self.cancel:
            raise RuntimeError("stopped by user")
        if rc != 0:
            raise RuntimeError(f"command failed (exit {rc}): {''.join(tail[-8:]).strip()}")
        return "".join(tail)

    def py(self, d, script, *args, **kw):
        return self.sh(d, [sys.executable, os.path.join(SCRIPTS, script), *map(str, args)], **kw)

    # ---- main loop
    def run(self):
        d, _ = load(self.cid)
        st_path = os.path.join(d, "state.json")
        open(os.path.join(d, "log.txt"), "a").write(
            f"\n===== {time.strftime('%H:%M:%S')}  Update: {', '.join(LABEL[s] for s in self.steps)} =====\n")
        for s in self.steps:
            if self.cancel:
                break
            self.current = LABEL[s]
            st = jload(st_path)
            st["steps"].setdefault(s, {})
            st["steps"][s].update(status="running", started=time.time(), error=None)
            jsave(st_path, st)
            t0 = time.time()
            self.cmds = []
            try:
                _, c = load(self.cid)
                dv = derive(c, d)
                info = getattr(self, "step_" + s)(d, c, dv) or {}
                status = info.pop("_status", "ok")
                err = None
            except Exception as e:  # noqa
                status, info, err = "error", {}, str(e)
                open(os.path.join(d, "log.txt"), "a").write(f"\n*** {LABEL[s]} failed: {e}\n")
            st = jload(st_path)
            st["steps"][s] = dict(status=status, info=info, error=err, seconds=round(time.time() - t0, 1),
                                  finished=time.strftime("%H:%M:%S"))
            if status == "ok":
                st.setdefault("commands", {})[s] = self.cmds
                write_commands(d, st)
            jsave(st_path, st)
            if status == "error":
                break
        self.current = None

    # ================================================================ steps
    def step_geometry(self, d, c, dv):
        g = c["geometry"]
        os.makedirs(os.path.join(d, "geom"), exist_ok=True)
        self.cmds.append("mkdir -p geom")
        src = g["source"]
        if src in ("naca2d", "naca_wing"):
            args = ["--naca", g["naca"], "--chord", g["chord"], "--dat", "geom/foil.dat"]
            if src == "naca_wing":
                args += ["--taper", g["taper"], "--semispan", g["semispan"], "--sweep", g["sweep"],
                         "--dihedral", g["dihedral"], "--twist", g["twist"], "--step", "geom/part.step"]
            self.py(d, "make_naca_wing.py", *args)
        elif src == "dat2d":
            P = _read_dat(os.path.join(d, g["cad_file"]))
            c0 = np.ptp(P[:, 0])
            P = (P - [P[:, 0].min(), 0]) / c0 * float(g["chord"])
            np.savetxt(os.path.join(d, "geom", "foil.dat"), P, fmt="%.7f",
                       header=f"{os.path.basename(g['cad_file'])} scaled to chord {g['chord']} m", comments="")
            self.cmds.append(f"# {g['cad_file']} scaled to chord {g['chord']} m -> geom/foil.dat (done by the app)")
        else:
            if not g.get("cad_file") or not os.path.exists(os.path.join(d, g["cad_file"])):
                raise RuntimeError("upload a STEP/IGES/STL file first (Geometry → Import)")
        out = {}
        if dv["dim"] == 2 or src == "naca_wing":
            P = _read_dat(os.path.join(d, "geom", "foil.dat"))
            out["airfoil"] = np.round(P, 6).tolist()
            out["n_points"] = len(P)
            out["t_over_c"] = float(_thickness(P))
        if dv["dim"] == 3:
            cad = os.path.join(d, "geom", "part.step") if src == "naca_wing" else os.path.join(d, g["cad_file"])
            gi = preview.geometry_info(cad, os.path.join(d, "geom", "geometry.json"))
            jsave(os.path.join(d, "geom", "geom_info.json"), gi)
            out.update(gi)
            out["viewer"] = "geom/geometry.json"
            if gi["n_solids"] > 1:
                out["note"] = f"{gi['n_solids']} solids: they will be fused for meshing."
            dv2 = derive(load(self.cid)[1], d)
            out["notes"] = dv2["notes"]
        return out

    def step_conditions(self, d, c, dv):
        fc = c["conditions"]
        args = ["--alt", fc["alt"], "--lref", dv["lref"], "--yplus", dv["target_yplus"], "-o", "cond.json"]
        args += ["--mach", fc["mach"]] if fc["spec"] == "mach" else ["--speed", fc["speed"]]
        if num(fc.get("T_override")):
            args += ["--T", fc["T_override"]]
        self.py(d, "flow_conditions.py", *args)
        return dict(cond=jload(os.path.join(d, "cond.json")))

    def step_mesh(self, d, c, dv):
        ms = c["mesh"]
        os.makedirs(os.path.join(d, "mesh"), exist_ok=True)
        self.cmds.append("mkdir -p mesh")
        cond = jload(os.path.join(d, "cond.json"))
        if dv["dim"] == 2:
            y1 = num(ms.get("y1"), cond["first_cell_height_m"])
            args = ["geom/foil.dat", "-o", "mesh/mesh.su2", "--y1", f"{y1:.4g}", "--level", dv["level"]]
            if num(ms.get("farfield")):
                args += ["--farfield", ms["farfield"]]
            self.py(d, "mesh_2d_airfoil.py", *args)
        else:
            cad = "geom/part.step" if dv["source"] == "naca_wing" else c["geometry"]["cad_file"]
            args = [cad, "--wall", dv["wall"], "-o", "mesh/mesh.su2", "--level", dv["level"],
                    "--lref", f"{dv['lref']:.5g}", "--threads", dv["threads"],
                    "--max-cells", f"{num(ms.get('max_cells'), 1.5e6):.3g}"]
            if dv["half"]:
                args.append("--half")
            if dv["scale"] != 1.0:
                args += ["--scale", dv["scale"]]
            wh = num(ms.get("wall_h"))
            if wh is None and dv["viscous"]:
                wh = 2.5 * cond["first_cell_height_m"]     # first cell ≈ 0.3-0.5 wall_h
                with open(os.path.join(d, "log.txt"), "a") as f:
                    f.write(f"RANS + wall functions: wall size {wh:.3g} m for y+ ≈ 50 (may exceed the cell budget)\n")
            if wh:
                args += ["--wall-h", f"{wh:.4g}"]
            if num(ms.get("farfield")):
                args += ["--farfield", ms["farfield"]]
            self.py(d, "mesh_3d.py", *args)
        info = preview.mesh_view(os.path.join(d, "mesh", "mesh.su2"), dv["wall"],
                                 os.path.join(d, "mesh", "mesh_view.json"),
                                 os.path.join(d, "mesh", "mesh.png"), chord=dv["chord"])
        if dv["dim"] == 3:
            info["viewer"] = "mesh/mesh_view.json"
        else:
            info["image"] = "mesh/mesh.png"
        return info

    def step_setup(self, d, c, dv):
        sv = c["solver"]
        os.makedirs(os.path.join(d, "run"), exist_ok=True)
        self.cmds.append("mkdir -p run")
        args = ["--mesh", "../mesh/mesh.su2", "--cond", "../cond.json", "--solver", dv["solver"],
                "--aoa", c["conditions"]["aoa"], "--lref", f"{dv['lref']:.6g}", "--sref", f"{dv['sref']:.6g}",
                "--xmom", f"{dv['xmom']:.6g}", "--walls", dv["wall"], "--far", "farfield",
                "--iter", dv["iterations"]]
        if dv["viscous"]:
            args += ["--turb", dv["turb"]]
        if dv["wall_functions"]:
            args.append("--wall-functions")
        if dv["dim"] == 3:
            args.append("--three-d")
            if num(c["conditions"].get("beta")):
                args += ["--beta", c["conditions"]["beta"]]
            if dv["half"]:
                args += ["--sym", "symmetry"]
        for k, flag in (("resmin", "--resmin"), ("cfl", "--cfl"), ("cfl_max", "--cfl-max")):
            if num(sv.get(k)) is not None:
                args += [flag, sv[k]]
        args += ["-o", "case.cfg"]
        self.py(d, "write_su2_config.py", *args, cwd=os.path.join(d, "run"))
        for f in glob.glob(os.path.join(d, "run", "*")):
            if os.path.basename(f) != "case.cfg":
                os.remove(f) if os.path.isfile(f) else shutil.rmtree(f)
        cfg = open(os.path.join(d, "run", "case.cfg")).read()
        return dict(cfg=cfg, solver=dv["solver"], turb=dv["turb"] if dv["viscous"] else None,
                    wall_functions=dv["wall_functions"], iterations=dv["iterations"])

    def step_solve(self, d, c, dv):
        run = os.path.join(d, "run")
        for f in ("history.csv", "flow.vtu", "surface_flow.vtu", "surface_flow.csv"):
            if os.path.exists(os.path.join(run, f)):
                os.remove(os.path.join(run, f))
        self.sh(d, ["SU2_CFD", "-t", str(dv["threads"]), "case.cfg"], cwd=run,
                display=f"SU2_CFD -t {dv['threads']} case.cfg   (live residuals in Solution Information)")
        h = preview.history(run)
        n = len(h["data"].get("Inner_Iter", [])) if h else 0
        return dict(iterations_run=n)

    def step_results(self, d, c, dv):
        run = os.path.join(d, "run")
        if dv["dim"] == 2:
            self.py(d, "postprocess_su2.py", "run", "--dim", 2, "--chord", dv["chord"], "--wall", dv["wall"])
        else:
            self.py(d, "postprocess_su2.py", "run", "--dim", 3, "--semispan", f"{dv['semispan']:.5g}",
                    "--chord-root", f"{dv['chord_root']:.5g}", "--cref", f"{dv['lref']:.5g}", "--wall", dv["wall"])
            try:
                preview.cfd_surface(run, os.path.join(run, "results", "surface_view.json"))
            except Exception as e:
                open(os.path.join(d, "log.txt"), "a").write(f"3D viewer export skipped: {e}\n")
        s = jload(os.path.join(run, "results", "summary.json"), {})
        est = estimate(c, dv, d)
        checks = []
        checks.append(dict(name="Iterative convergence", ok=bool(s.get("converged")),
                           detail=s.get("convergence_note", "")))
        yp = s.get("yplus_mean")
        if yp is not None and dv["viscous"]:
            ok = (yp < 2.5) if not dv["wall_functions"] else (15 < yp < 300)
            checks.append(dict(name="Wall resolution (y+)", ok=ok,
                               detail=f"mean y+ {yp:.3g}, max {s.get('yplus_max', 0):.3g}; target "
                                      f"{'≈1 (resolved wall)' if not dv['wall_functions'] else '30–300 (wall functions)'}"))
        if est.get("CL") is not None and s.get("CL") is not None:
            CLe, CLc = est["CL"], s["CL"]
            if abs(CLe) < 0.05:
                ok = abs(CLc) < 0.08
                det = f"CFD {CLc:.4f} vs estimate {CLe:.4f}"
            else:
                ratio = CLc / CLe
                ok = 0.8 <= ratio <= 1.2
                det = f"CFD CL {CLc:.4f} vs {est['method']} {CLe:.4f} (ratio {ratio:.2f})"
                if not 0.5 <= ratio <= 2:
                    det += " — 2× gap: check reference area, units, α axis"
            checks.append(dict(name="Lift sanity check", ok=ok, detail=det + ". " + est.get("note", "")))
        jsave(os.path.join(run, "results", "checks.json"), dict(checks=checks, estimate=est))
        imgs = sorted(os.path.relpath(p, d) for p in glob.glob(os.path.join(run, "results", "*.png")))
        return dict(summary=s, checks=checks, estimate=est, images=imgs,
                    viewer="run/results/surface_view.json" if dv["dim"] == 3 and
                    os.path.exists(os.path.join(run, "results", "surface_view.json")) else None)

    def step_polar(self, d, c, dv):
        """α sweep: one SU2 run per angle, each restarted from the nearest converged one (skill §5)."""
        raw = str(c["conditions"].get("polar") or "").replace(";", ",")
        alphas = sorted({round(float(x), 3) for x in raw.split(",") if x.strip()})
        if not alphas:
            return dict(_status="skipped", reason="no angles listed (Flow Conditions → Polar α list)")
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        base_a = float(c["conditions"]["aoa"])
        root = os.path.join(d, "run", "polar")
        if os.path.exists(root):
            shutil.rmtree(root)
        os.makedirs(root)
        s0 = jload(os.path.join(d, "run", "results", "summary.json"), {})
        done = {base_a: dict(alpha=base_a, CL=s0.get("CL"), CD=s0.get("CD"), CM=s0.get("CM"),
                             converged=s0.get("converged"), dir="run")}
        # march outward from the design angle so each restart is close to its neighbour
        order = sorted([a for a in alphas if a != base_a], key=lambda a: (abs(a - base_a), a))
        for a in order:
            if self.cancel:
                raise RuntimeError("stopped by user")
            prev = min(done, key=lambda x: abs(x - a))
            src = os.path.join(d, done[prev]["dir"], "restart.dat")
            sub = os.path.join(root, f"a{a:+06.2f}".replace("+", "p").replace("-", "m"))
            os.makedirs(sub)
            restart = os.path.exists(src)
            self.cmds.append(f"mkdir -p {os.path.relpath(sub, d)}")
            if restart:
                shutil.copy2(src, os.path.join(sub, "restart.dat"))
                self.cmds.append(f"cp {os.path.relpath(src, d)} {os.path.relpath(sub, d)}/restart.dat")
            cfg = open(os.path.join(d, "run", "case.cfg")).read()
            args = ["--mesh", "../../../mesh/mesh.su2", "--cond", "../../../cond.json", "--solver", dv["solver"],
                    "--aoa", a, "--lref", f"{dv['lref']:.6g}", "--sref", f"{dv['sref']:.6g}",
                    "--xmom", f"{dv['xmom']:.6g}", "--walls", dv["wall"], "--far", "farfield",
                    "--iter", dv["iterations"]] + (["--turb", dv["turb"]] if dv["viscous"] else []) + \
                   (["--wall-functions"] if dv["wall_functions"] else []) + \
                   (["--three-d"] + (["--sym", "symmetry"] if dv["half"] else []) if dv["dim"] == 3 else []) + \
                   (["--restart"] if restart else []) + ["-o", "case.cfg"]
            for k, flag in (("resmin", "--resmin"), ("cfl", "--cfl"), ("cfl_max", "--cfl-max")):
                if num(c["solver"].get(k)) is not None:
                    args += [flag, c["solver"][k]]
            self.py(d, "write_su2_config.py", *args, cwd=sub)
            self.sh(d, ["SU2_CFD", "-t", str(dv["threads"]), "case.cfg"], cwd=sub)
            h = preview.history(sub) or {}
            dd = h.get("data", {})
            last = lambda k: dd[k][-1] if dd.get(k) else None
            CM = last("CMy") if dv["dim"] == 3 else last("CMz")
            res = [dd[k] for k in dd if k.startswith("rms[")]
            drop = max((r[0] - r[-1]) for r in res) if res else 0
            cl = dd.get("CL", [])
            tail = cl[-max(20, len(cl) // 20):] if cl else []
            drift = (max(tail) - min(tail)) / max(abs(tail[-1]), 1e-9) if tail else 1
            done[a] = dict(alpha=a, CL=last("CL"), CD=last("CD"), CM=CM, dir=os.path.relpath(sub, d),
                           converged=bool(drop >= 2 and drift < 5e-3), restart_from=prev)
        rows = [done[a] for a in sorted(done)]
        np.savetxt(os.path.join(root, "polar.csv"), [[r["alpha"], r["CL"] or np.nan, r["CD"] or np.nan, r["CM"] or np.nan] for r in rows],
                   delimiter=",", header="alpha_deg,CL,CD,CM", comments="", fmt="%.6g")
        A = [r["alpha"] for r in rows]
        fig, ax = plt.subplots(1, 3, figsize=(14, 4.2), dpi=120)
        ax[0].plot(A, [r["CL"] for r in rows], "o-"); ax[0].set_xlabel("α [°]"); ax[0].set_ylabel("CL"); ax[0].set_title("Lift curve")
        ax[1].plot([r["CD"] for r in rows], [r["CL"] for r in rows], "o-"); ax[1].set_xlabel("CD"); ax[1].set_ylabel("CL"); ax[1].set_title("Drag polar")
        ax[2].plot(A, [r["CM"] for r in rows], "o-"); ax[2].set_xlabel("α [°]"); ax[2].set_ylabel("CM"); ax[2].set_title("Pitching moment")
        for a_, r in zip(ax, [None] * 3):
            a_.grid(alpha=.3)
        for r in rows:
            if not r["converged"]:
                ax[0].plot(r["alpha"], r["CL"], "rx", ms=10)
        fig.suptitle("Polar" + (" (red ×: not converged)" if any(not r["converged"] for r in rows) else ""))
        fig.tight_layout(); fig.savefig(os.path.join(root, "polar.png")); plt.close(fig)
        note = ("3D drag is not reliable on coarse tets — read the lift curve and moments." if dv["dim"] == 3 and not dv["viscous"]
                else "Steady RANS past stall is unreliable; treat the points after CL_max as indicative.")
        return dict(rows=rows, images=["run/polar/polar.png"], csv="run/polar/polar.csv", note=note)

    def step_structure(self, d, c, dv):
        if not dv["structure"]:
            return dict(_status="skipped", reason="structure disabled, 2D case, or no STEP solid")
        stc = c["structure"]
        cad = "geom/part.step" if dv["source"] == "naca_wing" else c["geometry"]["cad_file"]
        if os.path.exists(os.path.join(d, "fea")):
            shutil.rmtree(os.path.join(d, "fea"))
        args = [cad, "--cfd-run", "run", "--model", stc["model"], "--material", stc["material"],
                "--load-factor", stc["load_factor"], "--out", "fea", "--clamp-axis", stc["clamp_axis"]]
        if stc["model"] == "shell":
            args += ["--thickness", stc["thickness"]]
        if dv["scale"] != 1.0:
            args += ["--scale", dv["scale"]]
        if num(stc.get("h")):
            args += ["--h", stc["h"]]
        cv = num(stc.get("clamp_value"))
        if cv is None and dv["source"] != "naca_wing":
            gi = jload(os.path.join(d, "geom", "geom_info.json"), {})
            ax = "xyz".index(stc["clamp_axis"])
            cv = gi.get("bbox", [0] * 6)[ax] * dv["scale"] + 1e-6
        if cv is not None:
            args += ["--clamp-y", f"{cv:.6g}"]
        for k, flag in (("E", "--E"), ("nu", "--nu"), ("allowable", "--yield-stress")):
            if num(stc.get(k)) is not None:
                args += [flag, stc[k]]
        self.py(d, "fea_from_cfd.py", *args)
        f = jload(os.path.join(d, "fea", "fea_summary.json"), {})
        s = jload(os.path.join(d, "run", "results", "summary.json"), {})
        cond = jload(os.path.join(d, "cond.json"), {})
        checks = []
        if s.get("CL") is not None and cond:
            Fcfd = cond["q_Pa"] * dv["sref"] * math.hypot(s["CL"], s.get("CD", 0)) * float(stc["load_factor"])
            Fapp = float(np.linalg.norm(f.get("applied_force_N", [0, 0, 0])))
            err = abs(Fapp - Fcfd) / Fcfd if Fcfd else 1
            checks.append(dict(name="Load transfer (applied vs CFD force)", ok=err < 0.05,
                               detail=f"applied {Fapp:.4g} N vs CFD q·S·|C_R|·n = {Fcfd:.4g} N ({err*100:.1f} %)"))
        fb = f.get("force_balance_error")
        if fb is not None:
            checks.append(dict(name="Force balance (reactions)", ok=fb < 0.01, detail=f"{fb*100:.2f} %"))
        rf = f.get("reserve_factor_away_from_clamp")
        if rf is not None:
            checks.append(dict(name="Strength (RF away from clamp)", ok=rf >= 1.0,
                               detail=f"RF = {rf:.2f} ({f['max_von_mises_away_from_clamp_Pa']/1e6:.1f} MPa vs "
                                      f"{f['allowable_Pa']/1e6:.0f} MPa allowable)"))
        if stc["model"] == "shell":
            checks.append(dict(name="Buckling", ok=None,
                               detail="Not analysed: thin skins in compression (upper surface, +g) need a buckling check."))
        imgs = sorted(os.path.relpath(p, d) for p in glob.glob(os.path.join(d, "fea", "*.png")))
        return dict(summary=f, checks=checks, images=imgs,
                    viewer="fea/viewer.json" if os.path.exists(os.path.join(d, "fea", "viewer.json")) else None)

    def step_report(self, d, c, dv):
        import report
        report.write(d, c, dv, jload(os.path.join(d, "state.json")))
        return dict(markdown="report/report.md", html="report/report.html")

    def step_handoff(self, d, c, dv):
        name = re.sub(r"[^A-Za-z0-9]+", "_", c["name"]).strip("_") or "case"
        if os.path.exists(os.path.join(d, "handoff")):
            shutil.rmtree(os.path.join(d, "handoff"))
        self.py(d, "make_handoff.py", "--case", ".", "--name", name, "--commands", "commands.sh",
                "--out", "handoff", record=False)
        return dict(zip=f"handoff/{name}.zip",
                    size_mb=round(os.path.getsize(os.path.join(d, "handoff", name + ".zip")) / 1e6, 2))


def write_commands(d, st):
    """commands.sh = the latest successful command(s) of every step, in pipeline order."""
    L = ["#!/usr/bin/env bash", "# Commands run by AeroSim Workbench, in order. Run from the case folder;",
         "# SKILL points at the aircraft-cfd-fea scripts (the handoff package puts them in ./scripts).",
         "set -e", 'SKILL=${SKILL:-scripts}', 'export PATH="${SU2_RUN:-$HOME/tools/su2/bin}:$PATH"']
    for s in STEPS:
        cmds = st.get("commands", {}).get(s)
        if cmds:
            L.append(f"\n# ---- {LABEL[s]}")
            L += cmds
    open(os.path.join(d, "commands.sh"), "w").write("\n".join(L) + "\n")


def _thickness(P):
    i = int(np.argmin(P[:, 0]))
    up, lo = P[:i + 1][::-1], P[i:]
    x = np.linspace(P[:, 0].min(), P[:, 0].max(), 200)
    return float(np.max(np.interp(x, up[:, 0], up[:, 1]) - np.interp(x, lo[:, 0], lo[:, 1])) / np.ptp(P[:, 0]))


# ===================================================================== public API
def run_steps(cid, upto=None, only=None):
    d, c = load(cid)
    with _lock:
        if cid in _jobs and _jobs[cid].alive():
            raise RuntimeError("a job is already running for this case")
        st = jload(os.path.join(d, "state.json"))
        dv = derive(c, d)
        if only:
            steps = [only]
        else:
            last = STEPS.index(upto) if upto else len(STEPS) - 1
            # start at the first step that is not up to date
            first = next((i for i, s in enumerate(STEPS[:last + 1])
                          if st["steps"].get(s, {}).get("status") not in ("ok", "skipped")), last)
            target = STEPS[last]
            steps = [s for s in STEPS[first:last + 1]
                     if st["steps"].get(s, {}).get("status") not in ("ok",) or s in ("report", "handoff") or s == target]
        if not dv["structure"]:
            pass  # the structure step marks itself skipped
        job = Job(cid, steps)
        _jobs[cid] = job
        job.thread.start()
    return steps


def stop(cid):
    j = _jobs.get(cid)
    if j:
        j.stop()


def state(cid):
    d, c = load(cid)
    st = jload(os.path.join(d, "state.json"), dict(steps={}))
    j = _jobs.get(cid)
    running = bool(j and j.alive())
    for s in STEPS:
        e = st["steps"].get(s)
        if e and e.get("status") in ("running",) and not running:
            e["status"] = "error"; e["error"] = "interrupted (server restarted?)"
    queued = []
    if running:
        queued = [s for s in j.steps if st["steps"].get(s, {}).get("status") != "running"
                  and j.steps.index(s) > j.steps.index(next((x for x in j.steps if st["steps"].get(x, {}).get("status") == "running"), j.steps[0]))]
    dv = derive(c, d)
    dv.pop("cond", None)
    return dict(id=cid, settings=c, derived=dv, steps=st["steps"], running=running,
                queued=queued, step_order=STEPS, labels=LABEL, materials=MATERIALS)


def log_tail(cid, start=0):
    d, _ = load(cid)
    p = os.path.join(d, "log.txt")
    if not os.path.exists(p):
        return dict(text="", next=0)
    size = os.path.getsize(p)
    start = int(start)
    if start > size:
        start = 0
    if size - start > 200_000:
        start = size - 200_000
    with open(p, "rb") as f:
        f.seek(start)
        txt = f.read().decode("utf-8", "replace")
    return dict(text=txt, next=size)
