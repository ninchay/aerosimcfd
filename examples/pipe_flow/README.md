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
```

Options: `mesh_pipe.py --L 2.2 --D 0.5`, `run_pipe.py --mach 0.5 --L 2.2 --D 0.5`.
