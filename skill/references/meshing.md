# Meshing rules

## Wall spacing

`flow_conditions.py --yplus <target>` gives the first cell height y₁ from a
flat-plate skin-friction estimate on the reference length.

| Wall treatment | Target y+ | Where |
|---|---|---|
| Resolved (low-Re model) | ≈ 1 (≤ 2) | 2D RANS (`mesh_2d_airfoil.py --y1`) |
| Wall functions | 30–300 | 3D RANS on tets (`--wall-functions`) |
| Inviscid | n/a | Euler |

Always read the achieved y+ back from the results (`summary.json`) — the
estimate can be off by 2× near the leading edge and at high α.

## 2D airfoil mesh (`mesh_2d_airfoil.py`)

- Quad layer: grows from y₁ at ratio 1.10–1.20 to ~4 % chord, then triangles.
- Surface: transfinite "Bump" distribution clustered at LE and TE (Gmsh does
  not put nodes at spline points, so this has to be explicit).
- Farfield: circle at 100 chords (pressure/characteristic farfield).
- Levels: coarse ≈ 20 k, medium ≈ 35 k, fine ≈ 70 k cells.

## 3D mesh (`mesh_3d.py`)

- Box farfield at ~12 reference lengths (≥ 10), 1.5× that downstream.
- Wall size ≈ MAC/40 (coarse), /70 (medium), /120 (fine); curvature
  refinement adds points at the LE and tip; growth limited by the level.
- Half model: body cut on y = 0, symmetry plane marker `symmetry`.
- The script prints a cell estimate and stops above `--max-cells` (default
  2.5 M) so the sandbox does not run out of memory. The estimate is
  conservative (the test wing estimated 0.18 M and produced 69 k).

### Limitation: no prism layers in 3D

Gmsh's boundary-layer field is 2D only; reliable 3D prism layers need a
mesher built for it. For a y+≈1 3D RANS case:

1. Run the coarse tet case here (Euler or wall functions) to get the picture.
2. Hand off (`make_handoff.py`) and rebuild the volume mesh with prism layers
   (ANSYS Meshing / Fluent Meshing, Pointwise, snappyHexMesh, cfMesh), export
   SU2 or CGNS, reuse the same `case.cfg` without `--wall-functions`.

## Mesh independence

For a number someone will design to, run two or three levels with the same
setup. Report CL, CD at each; if the change between the two finest is < 1 %
(CL) and < 2–3 % (CD), the result is mesh-converged for that purpose.
Richardson extrapolation / GCI (Roache) with refinement ratio r:
GCI = 1.25 |ε| / (r^p − 1), p from three levels.
