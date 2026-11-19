# Straight pipe, inlet Mach 0.5 (internal flow example)

The Workbench app is set up for external aerodynamics (airfoils and wings in a
farfield). This example uses the same toolchain (Gmsh → SU2) for an internal
flow: a straight pipe, L = 2.2 m, D = 0.5 m, air at ISA sea level, inlet M 0.5.

- Axisymmetric 2D, compressible RANS with Spalart–Allmaras, resolved wall (y+ ≈ 1).
- Inlet: total pressure / temperature of the M 0.5 state (p = 101 325 Pa, T = 288.15 K).
- Outlet: static pressure, adjusted by `run_pipe.py` until the inlet Mach number is 0.5.
- Wall: adiabatic, no-slip. Axis: symmetry.

```bash
python3 mesh_pipe.py          # pipe.su2 (220 × 90 quads, first cell 2 µm)
python3 run_pipe.py           # SU2 runs; needs SU2_CFD on PATH (./install.sh)
python3 post_pipe.py          # results/: contours, inlet→outlet plots, summary.json
python3 export_excel.py       # results/pipe_results.xlsx with all the data
```

Options: `mesh_pipe.py --L 2.2 --D 0.5`, `run_pipe.py --mach 0.5 --L 2.2 --D 0.5`.

## Result (inlet M 0.5, ISA sea level)

Converged outlet pressure 100 383.6 Pa (the default `--p_out`, so a rerun starts there).

| | Inlet (x = 0) | Outlet (x = 2.2 m) |
|---|---|---|
| Static pressure, area-avg | 101.30 kPa | 100.38 kPa (Δp = 914 Pa) |
| Bulk velocity | 170.3 m/s | 171.8 m/s |
| Centreline velocity | 170.5 m/s | 175.1 m/s |
| Mach, mass-avg | 0.500 | 0.507 |
| Mach, centreline | 0.501 | 0.515 |
| Temperature | 288.1 K | 287.9 K |
| Density | 1.225 kg/m³ | 1.214 kg/m³ |
| Mass flow | 40.95 kg/s | 40.96 kg/s (0.04 % imbalance) |

Wall y+ mean 0.86, max 1.6. Plots and `summary.json` are in `results/`.
