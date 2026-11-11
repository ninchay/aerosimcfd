#!/usr/bin/env bash
# Start AeroSim Workbench:  ./run.sh            -> http://localhost:8050
#                           ./run.sh --port 9000 --host 0.0.0.0   (share on your network)
cd "$(dirname "$0")"
export SU2_RUN="${SU2_RUN:-$HOME/tools/su2/bin}"
export PATH="$SU2_RUN:$PATH"
export PYTHONPATH="$SU2_RUN:$PYTHONPATH"
command -v SU2_CFD >/dev/null || echo "warning: SU2_CFD not found – run ./install.sh first (or set SU2_RUN)"
command -v ccx >/dev/null || echo "warning: CalculiX (ccx) not found – structural steps will fail"
exec python3 server.py "$@"
