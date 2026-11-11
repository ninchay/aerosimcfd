#!/usr/bin/env bash
# Install the open-source toolchain used by the aircraft-cfd-fea skill.
#   Gmsh 4.x   – CAD import (STEP/STL), meshing, writes .su2 meshes
#   SU2 8.x    – compressible RANS / Euler CFD solver
#   CalculiX   – structural FEA (ccx)
#   meshio, scikit-fem, numpy, scipy, matplotlib – I/O, mapping, plots
# Safe to run more than once; skips what is already installed.
# Usage: source scripts/setup_env.sh      (so the PATH export sticks)
set -e
SU2_VERSION="${SU2_VERSION:-8.1.0}"
TOOLS="${TOOLS:-$HOME/tools}"
mkdir -p "$TOOLS"

pip install --break-system-packages -q gmsh meshio numpy scipy matplotlib 2>/dev/null || \
  pip install -q gmsh meshio numpy scipy matplotlib

# gmsh's Python wheel needs a few X/GL libraries even when run headless,
# and CalculiX comes from apt.
need_apt=""
python -c "import gmsh" 2>/dev/null || need_apt="yes"
command -v ccx >/dev/null 2>&1 || need_apt="yes"
if [ -n "$need_apt" ] && command -v apt-get >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo"
  $SUDO apt-get update -q >/dev/null 2>&1 || true
  $SUDO apt-get install -y -q libglu1-mesa libxcursor1 libxinerama1 libxft2 calculix-ccx >/dev/null
fi

if [ ! -x "$TOOLS/su2/bin/SU2_CFD" ]; then
  curl -sL -o "$TOOLS/su2.zip" \
    "https://github.com/su2code/SU2/releases/download/v${SU2_VERSION}/SU2-v${SU2_VERSION}-linux64.zip"
  unzip -q -o "$TOOLS/su2.zip" -d "$TOOLS/su2" && rm -f "$TOOLS/su2.zip"
fi
export SU2_RUN="$TOOLS/su2/bin"
export PATH="$SU2_RUN:$PATH"
export PYTHONPATH="$SU2_RUN:$PYTHONPATH"

python -c "import gmsh; gmsh.initialize(); print('gmsh', gmsh.__version__); gmsh.finalize()"
SU2_CFD --help 2>&1 | head -1
command -v ccx >/dev/null && echo "CalculiX: $(command -v ccx)"
echo "CPU cores: $(nproc)   RAM: $(free -g | awk '/Mem/{print $2}') GB"
