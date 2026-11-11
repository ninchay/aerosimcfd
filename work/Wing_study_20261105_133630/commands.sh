#!/usr/bin/env bash
# Commands run by AeroSim Workbench, in order. Run from the case folder;
# SKILL points at the aircraft-cfd-fea scripts (the handoff package puts them in ./scripts).
set -e
SKILL=${SKILL:-scripts}
export PATH="${SU2_RUN:-$HOME/tools/su2/bin}:$PATH"
