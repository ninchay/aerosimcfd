# AeroSim Workbench

A local web app that puts an ANSYS-Workbench-style interface on the
**aircraft-cfd-fea** pipeline: Gmsh meshing → SU2 CFD → CalculiX structural
analysis, with the same checks, report and rerunnable package the skill produces.

```
Geometry → Flow Conditions → Mesh → Analysis Settings → Solution → Results & Checks
                                                       → Polar Sweep (α)
                                                       → Static Structural (air loads → stress/strain)
                                                       → Report → Handoff Package
```

## Install and run

Linux (Ubuntu/Debian) or Windows through **WSL2**. Python 3.9+.

```bash
./install.sh        # once: Gmsh, SU2 8.1, CalculiX, Python libraries (~2–5 min)
./run.sh            # then open http://localhost:8050
```

`./run.sh --host 0.0.0.0 --port 8050` makes it reachable from other machines on
your network (there is no login, so only do this on a trusted network).

macOS (Intel or Apple Silicon): the same two commands. `./install.sh` sets up
Miniforge (unless you already have conda) with a `aerosim` environment holding
the Python libraries, Gmsh and CalculiX from conda-forge, and downloads SU2's
macOS build into `~/tools/su2`. SU2 publishes only an Intel Mac build, so on Apple
Silicon the installer also installs Rosetta 2. `./run.sh` finds all of it by
itself, so there is no environment to activate.

## Using it (same rhythm as ANSYS)

| Area | What it does |
|---|---|
| **Ribbon** | New / open / delete project · Import CAD · Generate Mesh · **Solve** · Structural · Update All · Stop · Report · Package · view orientation |
| **Outline** (left top) | The project tree. Status icons like Workbench: ✔ up to date, ⚡ inputs changed (needs update), ? not run, ◌ running, ✖ failed |
| **Details** (left bottom) | Property grid of the selected item. Blank fields use the skill's automatic choice, shown in grey italics. Every item has an **Update** button that runs the pipeline up to that point |
| **Graphics** | Interactive 3D (rotate / pan / zoom) with banded ANSYS-style legend for surface Cp, Mach, pressure, von Mises stress, deformation (scalable), strain; images for 2D contours, streamlines, Cp plots, loading |
| **Messages / Solution Information / Worksheet** | Live solver log · live residual and CL plot with an ETA · the file behind the selected item (SU2 config, cond.json, summary.json, commands.sh) |

Typical 3D wing study: **New → 3D wing** → set NACA, chord, taper, span, sweep in
*Geometry* → Mach / altitude / α in *Flow Conditions* → **Solve** → check *Results &
Checks* → set material and skin thickness under *Static Structural* → **Structural**
→ **Report** / **Package**. For a UAV or VTOL part: **Import** a STEP file (cut on
y = 0 for a half model; mm is detected automatically).

## What the app decides for you (from the skill)

- ISA atmosphere, Sutherland viscosity, Reynolds number, first-cell height for the target y+.
- 2D airfoil → RANS (SA) with a resolved wall (y+ ≈ 1). 3D → Euler on tetrahedra
  (pressure, lift, moments and loads are usable; 3D drag on coarse meshes is not).
  RANS in 3D uses wall functions. Below M 0.1 the incompressible solvers are used.
  Numerics (limiter, CFL) are picked from the Mach number.
- Reference area / chord / moment point from the geometry (MAC and half-wing area
  for the parametric wing, projected area for CAD); override under *Reference Values*.
- Checks after every solve: iterative convergence, wall y+, lift against
  thin-airfoil / lifting-line + Prandtl–Glauert; after FEA: applied load vs CFD
  force, reaction balance, reserve factor away from the clamp singularity, and a
  buckling reminder for thin skins.

## Files

```
server.py      web server (Python standard library)
pipeline.py    case model, the skill's decisions, step runner (records commands.sh)
preview.py     geometry / mesh / result readers for the 3D viewer
report.py      report.md + self-contained report.html
static/        the interface (HTML/CSS/JS, three.js bundled – works offline)
skill/         the aircraft-cfd-fea scripts and references the pipeline calls
work/<case>/   one folder per project: geom/ mesh/ run/ fea/ report/ handoff/ commands.sh
```

Every step is a plain command recorded in `work/<case>/commands.sh`, so a case
can be rerun or refined without the app (the **Package** button bundles it with
`run_all.sh`).

## Limits (said plainly)

- SU2's release build is serial: one core. 2D RANS runs a few iterations per
  second; for fine 3D meshes use the handoff package on a workstation/cluster.
- 3D meshes are tetrahedra only (no prism layers): good pressure and lift, rough drag.
- Fully turbulent RANS (no transition); steady RANS past stall is unreliable.
- Structure: one-way coupling, linear static, isotropic materials (composites as
  quasi-isotropic), no buckling, fatigue or ply failure.
- Rotors, propellers and hover are not supported yet.
# aerosimcfd
