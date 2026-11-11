#!/usr/bin/env bash
# One-time install of the solver toolchain for AeroSim Workbench.
#   Gmsh (meshing) · SU2 8.1 (CFD) · CalculiX (FEA) · numpy/scipy/matplotlib/meshio/pyvista/pandas
# Linux (Ubuntu/Debian) or Windows via WSL2. Needs internet; uses sudo for apt.
set -e
cd "$(dirname "$0")"
# the skill's installer calls `python`; make sure that resolves to python3
if ! command -v python >/dev/null 2>&1; then python() { python3 "$@"; }; fi
source skill/scripts/setup_env.sh
python3 -m pip install --break-system-packages -q pyvista pandas 2>/dev/null || python3 -m pip install -q pyvista pandas
# pyvista renders off-screen; on a headless server it may need these GL libraries
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo"
  $SUDO apt-get install -y -q libgl1 libxrender1 >/dev/null 2>&1 || true
fi
echo
echo "Install complete. Start the app with:  ./run.sh   then open http://localhost:8050"
