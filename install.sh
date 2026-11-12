#!/usr/bin/env bash
# One-time install of the solver toolchain for AeroSim Workbench.
#   Gmsh (meshing) · SU2 8.1 (CFD) · CalculiX (FEA) · numpy/scipy/matplotlib/meshio/pyvista/pandas
# Linux (Ubuntu/Debian), Windows via WSL2, or macOS (Intel or Apple Silicon). Needs internet.
# Safe to run again: it skips what is already installed.
set -e
cd "$(dirname "$0")"
SU2_VERSION="${SU2_VERSION:-8.1.0}"
TOOLS="${TOOLS:-$HOME/tools}"

# ---------------------------------------------------------------- macOS
if [ "$(uname -s)" = "Darwin" ]; then
  ENV_NAME=aerosim
  mkdir -p "$TOOLS"

  # 1. Rosetta 2: SU2 publishes only an Intel Mac build; Apple Silicon runs it through Rosetta.
  if [ "$(uname -m)" = "arm64" ] && ! arch -x86_64 /usr/bin/true 2>/dev/null; then
    echo "==> Installing Rosetta 2 (SU2 needs it on Apple Silicon; macOS may ask for your password)"
    softwareupdate --install-rosetta --agree-to-license || sudo softwareupdate --install-rosetta --agree-to-license
  fi

  # 2. conda: use one that is already installed, otherwise install Miniforge into ~/miniforge3.
  CONDA=""
  for c in "$(command -v conda 2>/dev/null || true)" \
           "$HOME/miniforge3/bin/conda" "$HOME/mambaforge/bin/conda" \
           "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
           /opt/homebrew/Caskroom/miniforge/base/bin/conda /usr/local/Caskroom/miniforge/base/bin/conda \
           /opt/homebrew/Caskroom/miniconda/base/bin/conda /usr/local/Caskroom/miniconda/base/bin/conda; do
    if [ -n "$c" ] && [ -x "$c" ]; then CONDA="$c"; break; fi
  done
  if [ -z "$CONDA" ]; then
    echo "==> Installing Miniforge (Python package manager) into ~/miniforge3"
    curl -fsSL -o "$TOOLS/miniforge.sh" \
      "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-$(uname -m).sh"
    bash "$TOOLS/miniforge.sh" -b -p "$HOME/miniforge3"
    rm -f "$TOOLS/miniforge.sh"
    CONDA="$HOME/miniforge3/bin/conda"
  fi
  echo "==> Using conda: $CONDA"

  # 3. Python libraries, Gmsh and CalculiX (ccx) from conda-forge, in their own environment.
  PKGS="python=3.11 numpy scipy matplotlib pandas meshio pyvista python-gmsh calculix"
  if "$CONDA" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "==> Updating conda environment '$ENV_NAME'"
    "$CONDA" install -y -q -n "$ENV_NAME" --override-channels -c conda-forge $PKGS
  else
    echo "==> Creating conda environment '$ENV_NAME' (a few minutes the first time)"
    "$CONDA" create -y -q -n "$ENV_NAME" --override-channels -c conda-forge $PKGS
  fi
  ENV_BIN="$("$CONDA" run -n "$ENV_NAME" python -c 'import sys, os; print(os.path.join(sys.prefix, "bin"))')"

  # 4. SU2 (macOS release build). Replace a Linux build left by an earlier attempt.
  if ! file "$TOOLS/su2/bin/SU2_CFD" 2>/dev/null | grep -q Mach-O; then
    echo "==> Downloading SU2 $SU2_VERSION for macOS"
    rm -rf "$TOOLS/su2"
    curl -fsSL -o "$TOOLS/su2.zip" \
      "https://github.com/su2code/SU2/releases/download/v${SU2_VERSION}/SU2-v${SU2_VERSION}-macos64.zip"
    unzip -q -o "$TOOLS/su2.zip" -d "$TOOLS/su2" && rm -f "$TOOLS/su2.zip"
    xattr -dr com.apple.quarantine "$TOOLS/su2" 2>/dev/null || true
  fi
  SU2_RUN="$TOOLS/su2/bin"

  # 5. Tell run.sh where everything is.
  cat > .aerosim-env <<EOF
# written by install.sh – read by run.sh
ENV_BIN="$ENV_BIN"
SU2_RUN="$SU2_RUN"
EOF

  # 6. Check every piece.
  echo "==> Checking the install"
  "$ENV_BIN/python" -c "import numpy, scipy, matplotlib, pandas, pyvista, gmsh; gmsh.initialize(); print('gmsh', gmsh.__version__); gmsh.finalize()"
  "$SU2_RUN/SU2_CFD" --help 2>&1 | grep -m1 SU2 || { echo "SU2_CFD does not start"; exit 1; }
  [ -x "$ENV_BIN/ccx" ] && echo "CalculiX: $ENV_BIN/ccx" || { echo "CalculiX (ccx) missing"; exit 1; }
  echo
  echo "Install complete. Start the app with:  ./run.sh   then open http://localhost:8050"
  exit 0
fi

# ---------------------------------------------------------------- Linux / WSL2
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
