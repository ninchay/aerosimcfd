# Structural model (CalculiX via `fea_from_cfd.py`)

## Choosing the model

| Part | Model | Notes |
|---|---|---|
| Thin metal/composite skin wing, monocoque fuselage | `shell` + `--thickness` | Outer surface only. Without ribs/spars in the CAD the skin panels bulge; deflection is overpredicted and panel stresses dominate. Say so; add internal structure when known. |
| Solid or foam-core UAV wing, 3D-printed part | `solid` | C3D10 tets fill the CAD solid. |
| Spar, bracket, fitting, hinge, wing-fold joint | `solid` | Give the separate part CAD; loads from CFD only if it is wetted, else apply resultants by hand. |

If the user's description doesn't settle it, pick and state the assumption
(e.g. "treated as a 1.5 mm Al skin, no ribs").

## Materials built in (isotropic, room temperature)

| Key | E [GPa] | ν | ρ [kg/m³] | allowable [MPa] |
|---|---|---|---|---|
| Al7075-T6 | 71.7 | 0.33 | 2810 | 503 (yield) |
| Al2024-T3 | 73.1 | 0.33 | 2780 | 345 |
| Al6061-T6 | 68.9 | 0.33 | 2700 | 276 |
| Ti-6Al-4V | 113.8 | 0.342 | 4430 | 880 |
| Steel-4130 | 205 | 0.29 | 7850 | 460 |
| CFRP-quasi-iso | 50 | 0.30 | 1600 | 450 |
| GFRP-quasi-iso | 20 | 0.25 | 1900 | 250 |
| PLA-print | 3.5 | 0.36 | 1250 | 50 |

Override with `--E --nu --yield-stress`. Composite entries are a quasi-
isotropic laminate approximation: fine for stiffness and deflection, not for
ply failure — say so.

## Load cases

The CFD run is one flight point. Scale with `--load-factor`:
- Limit load = n_limit × 1g lift (e.g. n = 3.8 normal category, 2.5 transport,
  UAV per its spec). Ultimate = 1.5 × limit (CS/FAR 23/25 practice).
- Only scale if the CFD point is the 1g trim condition; otherwise rerun CFD
  at the α that gives the required lift.
- Inertia relief (structure + fuel weight) is not included: conservative for
  wing bending.

## Checks the script reports

- Applied aero force vs CFD (CL·q·S): should agree within a few %.
- `force_balance_error`: reactions vs applied, should be < 1 %.
- `mapping_max_distance_m`: CFD-to-structure surface gap; large values mean
  the two geometries differ (wrong units / different CAD).
- Stress at the clamp corner is a singularity; quote
  `max_von_mises_away_from_clamp_Pa` and its reserve factor.

## Not covered (flag when relevant)

Buckling of compressed skins (upper surface in positive g!), fatigue,
joints/fasteners, thermal loads, aeroelastic deformation feedback (this is
one-way coupling), dynamic gusts, flutter.
