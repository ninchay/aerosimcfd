#!/usr/bin/env python3
"""Bundle a finished case so it can be rerun (finer) on a bigger machine.

Copies the mesh(es), SU2 configs, FEA input, results, report and the skill's
scripts into one folder + zip, and writes run_all.sh / README.md describing
exactly how the case was built and how to refine it.

Example
  python make_handoff.py --case work/wing_m080 --name wing_m080 \
      --commands commands.sh --out handoff
`--commands` is a text file with the exact command lines used (the skill
records them as it goes), so the user can reproduce every step.
"""
import argparse, os, shutil, glob, datetime

KEEP = ("*.su2", "*.cfg", "*.step", "*.stp", "*.stl", "*.dat", "*.json", "*.inp",
        "*.md", "*.csv", "*.png")
SKIP = ("restart.dat", "model.dat", "nodal_results.csv")   # regenerable, large


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", required=True, help="case directory")
    ap.add_argument("--name", required=True)
    ap.add_argument("--commands", help="file with the command lines used")
    ap.add_argument("--out", default="handoff")
    ap.add_argument("--max-mb", type=float, default=60, help="skip files bigger than this")
    a = ap.parse_args()
    dst = os.path.join(a.out, a.name)
    os.makedirs(dst, exist_ok=True)
    skipped = []
    for root, _, files in os.walk(a.case):
        if os.path.abspath(root).startswith(os.path.abspath(a.out)):
            continue
        for f in files:
            src = os.path.join(root, f)
            if f in SKIP or not any(glob.fnmatch.fnmatch(f, k) for k in KEEP):
                continue
            if os.path.getsize(src) > a.max_mb * 1e6:
                skipped.append(src); continue
            rel = os.path.relpath(src, a.case)
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            shutil.copy2(src, os.path.join(dst, rel))
    here = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(here, os.path.join(dst, "scripts"), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    cmds = open(a.commands).read() if a.commands else "# (commands not recorded)\n"
    with open(os.path.join(dst, "run_all.sh"), "w") as f:
        f.write("#!/usr/bin/env bash\n# Reproduce this case. Edit NP for your core count.\n"
                "set -e\nNP=${NP:-8}\nsource scripts/setup_env.sh\n"
                "# SU2 with MPI:  mpirun -n $NP SU2_CFD case.cfg\n"
                "# SU2 threads:   SU2_CFD -t $NP case.cfg\n\n" + cmds)
    os.chmod(os.path.join(dst, "run_all.sh"), 0o755)
    with open(os.path.join(dst, "README.md"), "w") as f:
        f.write(f"# {a.name} – CFD/FEA case package\n\nCreated {datetime.date.today()}.\n\n"
                "* `run_all.sh` – every command used, in order\n"
                "* `scripts/` – the pipeline (Gmsh, SU2, CalculiX helpers)\n"
                "* `report.md` – setup, checks and results (if present)\n\n"
                "## Refining on a bigger machine\n"
                "1. Re-mesh with `--level fine` (or smaller `--wall-h`), keep everything else.\n"
                "2. Run SU2 in parallel (`mpirun -n NP SU2_CFD case.cfg`; the release zip from\n"
                "   su2code.github.io includes MPI binaries, or build with `-Dwith-mpi=enabled`).\n"
                "3. Compare CL/CD between levels: if they change < 1-2 %, the coarse answer holds.\n"
                "4. For y+~1 RANS in 3D, rebuild the volume mesh with prism layers in a mesher\n"
                "   that supports them (ANSYS Meshing/Fluent Meshing, Pointwise, snappyHexMesh,\n"
                "   cfMesh) and export to SU2/CGNS; drop `--wall-functions` from the config.\n")
        if skipped:
            f.write("\nNot included (too large; regenerate with run_all.sh):\n" +
                    "".join(f"* {s}\n" for s in skipped))
    z = shutil.make_archive(dst, "zip", a.out, a.name)
    print(f"wrote {z}" + (f" (skipped {len(skipped)} large files)" if skipped else ""))


if __name__ == "__main__":
    main()
