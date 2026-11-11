# Verification and validation

## Checklist before presenting results

1. `summary.json → converged` is true, or you explain why not.
2. y+ matches the wall treatment (≈1 resolved; 30–300 wall functions).
3. CL within ~15 % of a hand estimate (method_selection.md); CD of plausible
   magnitude (≥ the skin-friction floor for RANS).
4. Reference area / length / moment point are what the report states.
5. Coupled cases: applied force ≈ CFD force, force balance < 1 %.
6. A mesh-level comparison for any number used in a design decision.

## Validation case: NACA 0012, M = 0.15, Re = 6×10⁶, fully turbulent

NASA Turbulence Modeling Resource (SA, fine-grid reference values):

| α | CL | CD |
|---|---|---|
| 0° | 0.000 | ≈ 0.0081 |
| 10° | ≈ 1.091 | ≈ 0.0123 |
| 15° | ≈ 1.55 | ≈ 0.021 |

Experiment (Ladson, transition-fixed) CL at 10° ≈ 1.07. Use this case to
check the installation and settings after any change to the scripts:

```
flow_conditions.py --alt 0 --mach 0.15 --lref 1 --yplus 1
make_naca_wing.py --naca 0012 --chord 1 --dat naca0012.dat
mesh_2d_airfoil.py naca0012.dat -o mesh.su2 --y1 4e-6 --level medium
write_su2_config.py --mesh mesh.su2 --mach 0.15 --aoa 10 --re 6e6 --lref 1 \
   --sref 1 --T 300 --walls airfoil --far farfield --iter 6000 --resmin -9
SU2_CFD case.cfg
```

Result with these exact commands (medium mesh, 36 k cells, ~4 min on 1 core):
CL = 1.089 (−0.1 %), CD = 0.0155 (+26 %), mean y+ 0.94, 5.6 orders residual
drop. Lift is mesh-converged; drag is not at this level (drag converges
slowest) — use `--level fine` for drag numbers.
