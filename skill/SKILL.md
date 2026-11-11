---
name: aircraft-cfd-fea
description: ANSYS-style aerodynamic and structural simulation for aircraft designers with open-source tools (Gmsh, SU2 RANS/Euler, CalculiX FEA). Takes CAD (STEP/STL) or airfoil/wing parameters, builds the mesh, sets up flight conditions (Mach, altitude, Reynolds, viscosity, turbulence model), solves, and returns pressure/velocity/Mach contours, streamlines, Cp plots, CL/CD/CM, then maps the air loads onto the structure for stress, strain and deflection, with a report and a rerunnable script package. Use whenever the user wants CFD, airflow, pressure distribution, lift/drag, shock location, flow visualisation, wing loads, or stress/strain/deflection of an aircraft part, wing, airfoil, UAV or VTOL, even if they just say "simulate", "run it like ANSYS/Fluent", "check the airflow", or "will this wing hold".
---

# Aircraft CFD + FEA

This skill turns Claude into a small, honest version of an ANSYS Workbench chain:

```
CAD / parameters → mesh (Gmsh) → flow setup → SU2 solve → post-processing
                                                   ↓ surface pressure
                         structural mesh → CalculiX static FEA → stress/strain
                                                   ↓
                                 report + rerunnable case package
```

The person is usually an aerospace engineer or student. They know the physics;
what they need from you is a correct setup, a converged and checked answer,
clear pictures, and a clear statement of how far the numbers can be trusted.
A beautiful contour from an unconverged run on a bad mesh is worse than no
answer, so the checks in step 6 are not optional.

All helper scripts live in `scripts/` (run any with `--help`). Read the
reference file named in each step when you reach it, not before.

## 0. Environment

Run `source scripts/setup_env.sh` once per session. It installs Gmsh, SU2,
CalculiX and the Python libraries, and prints the core count and RAM. Note
those numbers: they set what is feasible (step 2).

## 1. Intake — pin down the case before meshing

Get these from the request, the files, or a short question. Don't ask for
what you can reasonably default; state the defaults you chose.

| Item | Default if not given |
|---|---|
| Geometry: STEP/IGES/STL file, `.dat` airfoil, or wing parameters | — (ask) |
| CAD units | assume mm if the part is > 50 units long, else m; say so |
| Flight condition: Mach or speed, altitude (ISA) | — (ask) |
| Angle(s) of attack, sideslip | 0° and the user's design point |
| Reference area, chord, moment point | planform area, MAC, 25 % MAC |
| Physics: aero only, structure only, or coupled | what the question implies |
| Structure: material, skin thickness / solid, clamp location, load factor | see `references/structures.md` |

Write the case down at the top of the work folder as `case.md` (geometry,
conditions, references, choices). Record every command you run in
`commands.sh` as you go — the handoff package (step 9) is built from it.

## 2. Choose the method

Read `references/method_selection.md`. In short:

- Get freestream properties, Reynolds number and the first-cell height from
  `scripts/flow_conditions.py` (ISA, Sutherland viscosity) — never hand-compute.
- **2D airfoil**: full RANS, resolved wall (y+ ≈ 1), SA by default, SST for
  separation / high α. Cheap: minutes.
- **3D wing / body / aircraft**: tetrahedral mesh, so the wall cannot be
  resolved. Default to **Euler** (`EULER`, or `INC_EULER` below Mach 0.1) for
  pressure, lift, moments, shock position and loads for the structure. Use
  RANS (`--turb SA --wall-functions`) only when the user needs viscous
  effects (skin friction pattern, separation tendency) and say what it costs:
  in testing on a UAV wing at Re 4×10⁵ the wall cells sat at y+ ≈ 500 and
  wall-function RANS gave CL 0.49 where Euler gave 0.63 and lifting-line
  ≈ 0.65 — the over-thick boundary layer decambers the wing. Keep y+ ≤ ~150
  (smaller `--wall-h`) if lift from RANS matters. Avoid SST on these meshes:
  its eddy viscosity grew to ~10⁴ × laminar in the near field and it never
  converged; SA converged 6+ orders.
- **Trust levels on sandbox-size 3D meshes**: surface pressure, CL, moments
  and loads are usable (check against lifting-line); drag is not — numerical
  dissipation on coarse tets adds spurious drag (Euler CD 0.038 vs ≈ 0.018
  induced in the UAV test). Quote 3D CD only with a mesh study and the caveat.
- **Regime**: the config writer picks numerics from Mach (limiter and CFL for
  transonic/supersonic). Below Mach ≈ 0.1 use the incompressible solvers (`INC_EULER`, `INC_RANS`); the
  compressible solver is stiff there.
- **Budget**: on the 2-core / 8 GB class sandbox, stay under ~1–2 M cells in
  3D (`mesh_3d.py` estimates and refuses beyond `--max-cells`). If the user
  needs finer, run coarse here, then hand off (step 9). Tell the user the
  expected run time before starting anything longer than ~10 minutes.
  Measured on 2 cores: 2D RANS 36 k cells, 6000 it ≈ 4 min; 3D Euler 70 k
  tets, 1500 it ≈ 5 min; 3D SA 120 k tets ≈ 0.8 s/it; 410 k tets ≈ 2.5 s/it.
  A structural run of ~100 k nodes takes 1–2 min.
- Rotors / propellers / hover: not supported in this version — say so.

## 3. Geometry

- Airfoil: `make_naca_wing.py --naca 2412 --chord 1 --dat foil.dat`, or a UIUC
  `.dat` file scaled to the physical chord.
- Wing from parameters: `make_naca_wing.py ... --step wing.step` (root on
  y = 0, so it can be run as a half model with a symmetry plane).
- User CAD: inspect it first (bounding box, units, number of solids,
  watertight?). For a half model the body must be cut on y = 0. Strip small
  features that do not affect the flow (fasteners, fillets < 1 % chord) if
  meshing fails; tell the user what you removed.

## 4. Mesh

Read `references/meshing.md` for sizing rules and the 3D wall-layer limitation.

- 2D: `mesh_2d_airfoil.py foil.dat -o mesh.su2 --y1 <first_cell_height>
  --level medium` (quad boundary layer + triangles, farfield 100 chords).
- 3D: `mesh_3d.py part.step --half --wall wing -o mesh.su2 --level coarse
  --lref <MAC>` (add `--scale 0.001` for mm CAD).
- Look at the mesh before solving (render a close-up of the LE and TE in 2D;
  check the wall triangle count and SU2's mesh-quality printout in 3D).

## 5. Set up and run SU2

```
write_su2_config.py --mesh mesh.su2 --cond cond.json --aoa 4 \
   --lref <c_ref> --sref <S_ref> --xmom <x_ref> --walls wing \
   --far farfield [--sym symmetry] [--three-d] [--solver EULER|RANS] \
   [--turb SA|SST] [--wall-functions] -o case.cfg
SU2_CFD -t <cores> case.cfg > log.txt
```

- 2D reference area = chord (unit span). Half model: reference area = half-wing
  area; the forces are for the half.
- Run long solves in the background and monitor `history.csv`; do not chain
  sleeps. Polars (several α) are separate runs; restart from the nearest
  converged α (`--restart`, copy `restart.dat`) to save time.
- If the residual stalls early or oscillates, see the troubleshooting table in
  `references/method_selection.md` before changing anything at random.

## 6. Check the answer (always)

Run `postprocess_su2.py <run> --dim 2|3 ...`. It writes the pictures and
`results/summary.json` with a `converged` flag. Then go through
`references/verification.md`:

1. **Iterative convergence**: forces steady (drift < 0.1 %) and residuals down
   ≥ 3–4 orders (≥ 2 with flat forces is acceptable on transonic/limiter
   cases). If not converged, say so and don't present the numbers as results.
2. **Wall resolution**: y+ from the summary matches the wall treatment.
3. **Sanity**: compare with a quick estimate (thin-airfoil 2π α, lifting-line
   CLα for the aspect ratio, Prandtl–Glauert, known validation data). A 2× gap
   means a setup error (reference area, units, α axis), not "CFD being CFD".
4. **Mesh sensitivity** when the number matters for a decision: run a second
   level and report the change in CL/CD.

## 7. Structure (when loads → stress is wanted)

Read `references/structures.md` to choose the model and material, then:

```
fea_from_cfd.py part.step --cfd-run <run> \
   --model shell --thickness 0.0015 --material Al7075-T6 \
   --load-factor 1.5 --out fea
```

- `--model shell` for thin-walled skins/monocoque, `--model solid` for solid
  or thick parts (foam/composite-core UAV wings, spars, fittings, brackets).
  Decide from the user's description and say which assumption you made.
- Freestream pressure is read from the CFD far field (incompressible runs are
  already gauge pressure); pass `--p-inf` only to override.
- The script prints the applied force; it must match the CFD force (CL·q·S)
  within a few %, and the reaction must balance it (`force_balance_error`).
  If not, the mapping or normals are wrong — stop and fix.
- Quote strength from `max_von_mises_away_from_clamp_Pa` and its reserve
  factor; the clamp corner is an idealisation singularity.
- Linear static only: no buckling, no fatigue, no composites failure. Thin
  skins under compression must be flagged for a buckling check.

## 8. Report

Write `report.md` in the case folder with this structure (embed the images):

```
# <Case name>
## Summary            – 3-5 bullets: key numbers + the main caveat
## Geometry & references
## Flow conditions     – table from flow_conditions.py
## Mesh                – type, cell count, y+, image
## Solver setup        – solver, turbulence model, numerics, BCs
## Convergence & checks – residuals, force drift, sanity/validation comparison
## Aerodynamic results – CL, CD, CM, L/D table; contours, streamlines, Cp
## Structural results  – model, material, load case, max stress, RF, deflection
## Limitations & next steps
```

In chat, give the key numbers and the 2–3 most informative pictures (send the
image files), not the whole report. Keep the units SI throughout.

## 9. Handoff package

`make_handoff.py --case <dir> --name <name> --commands commands.sh --out handoff`
zips mesh, configs, FEA input, results, report and scripts with `run_all.sh`
and instructions for refining on a workstation or cluster. Send the zip.

## Scope reminders

Say plainly what a result can and cannot support: tet-only 3D meshes with wall
functions give good pressure and lift, rougher drag; fully turbulent RANS
misses laminar runs and transition at low Re (< ~5×10⁵); steady RANS past
stall is unreliable; the structural model is as good as its idealisation
(missing ribs/spars, isotropic composites). These caveats belong in the report
summary, not hidden at the end.
