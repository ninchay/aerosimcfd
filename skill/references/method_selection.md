# Method selection

## Solver by question

| Question | Solver | Why |
|---|---|---|
| Airfoil polar, Cp, separation onset | 2D RANS, y+≈1, SA (SST near stall) | cheap, fully resolved wall |
| Wing/aircraft lift, pressure, shock position, loads for FEA | 3D Euler | pressure-dominated; fastest |
| 3D viscous patterns (skin friction, separation tendency) | 3D RANS SA + wall functions | tet mesh cannot resolve y+≈1; keep y+ ≤ ~150 or lift drops (UAV test: −20 % at y+ 500) |
| Production-quality 3D drag | hand off: prism-layer mesh + RANS | needs a BL-capable mesher |
| Very low speed (M < 0.1, small UAV) | `INC_EULER` / `INC_RANS` | compressible solver gets stiff; incompressible pressure is gauge (p∞ = 0) |
| Rotors, propellers, hover | not in this version | needs actuator disk / rotating frame |

## Turbulence model

- **SA** (Spalart–Allmaras): default for attached aerospace flows; robust and
  well validated for airfoils and wings.
- **SST** (k-ω SST): better for adverse pressure gradients, separation, high α,
  bluff parts (fuselage aft bodies, nacelles). Use it on 2D or prism-layer
  meshes. On coarse 3D tetrahedral meshes with wall functions it blew up in
  testing (μt/μ ≈ 10⁴ through the near field, CD 5× too high, no
  convergence) even with flight-level freestream turbulence; SA converged
  6+ orders on the same mesh. Check `Eddy_Viscosity` in flow.vtu when using SST.
- Freestream turbulence for SST defaults to 0.1 % / μt/μ = 1 (free flight),
  not SU2's wind-tunnel defaults; override with `--tu --mut-ratio`.
- Both are fully turbulent. Below Re ≈ 5×10⁵ (small UAV, low speed) laminar
  runs and separation bubbles matter: tell the user CD will be overpredicted
  and CLmax uncertain; suggest comparing with XFOIL/NeuralFoil-type
  transition-aware tools.

## Numerics chosen by `write_su2_config.py`

| Regime | Scheme | Limiter | CFL (start → max) |
|---|---|---|---|
| M < 0.75 | Roe, MUSCL | Van Albada (edge) | 10 → 50 |
| M ≥ 0.75 | Roe, MUSCL | Venkatakrishnan (0.05) | 5 → 25 |
| INC_RANS | FDS, MUSCL | Van Albada | 10 → 50 |

Learned in testing: with no limiter on a hybrid quad/tri 2D mesh the NACA0012
case stalled at ~0.5 orders of residual drop; Van Albada edge converged 4+
orders in 600 iterations. Keep a limiter on unstructured meshes.

## Troubleshooting a run

| Symptom | Likely cause | Fix |
|---|---|---|
| Residual rises / NaN in first 50 it. | CFL too high, bad cells | `--cfl 2 --cfl-max 10`; check mesh quality printout |
| Residual stalls at 2–3 orders, forces flat | limiter chatter (transonic) | accept if force drift < 0.1 %; or raise `VENKAT_LIMITER_COEFF` |
| Forces oscillate periodically | real unsteadiness (separation, bluff body, high α) | lower α, or say steady RANS is not valid there |
| SST: k residual stuck high, μt/μ ≫ 1000 in the field | SST on coarse tets | switch to SA |
| 3D CD 2–3× a lifting-line + skin-friction estimate | spurious numerical drag on coarse tets | refine / hand off; trust CL, not CD |
| CL off by ~2× | reference area (half vs full), chord, AoA axis (3D AoA is in x-z) | check `REF_AREA`, `--three-d` |
| y+ ≫ target | wrong `--y1` (used other Re or chord) | recompute with `flow_conditions.py` |
| Very slow 3D | too many cells for the machine | coarser level; Euler first; hand off |

## Sanity estimates (for step 6)

- Thin airfoil: Cl ≈ 2π(α − α₀); NACA 4-digit α₀ ≈ −(camber %) degrees roughly.
- Finite wing (Helmbold): CLα = 2πA / (2 + √(A²(1+tan²Λ_c/2 − M²)/κ² + 4)), κ≈1.
- Compressibility: Cp ≈ Cp₀ / √(1 − M²) (subsonic, attached).
- Skin-friction drag floor: CD_f ≈ Cf_turb · S_wet/S_ref, Cf ≈ 0.074 Re^-0.2.
