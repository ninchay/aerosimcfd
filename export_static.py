#!/usr/bin/env python3
"""Export one finished case as a static, read-only copy of the Workbench UI.

    python export_static.py <case-id> <out-dir>

The folder can be opened from any static web host (GitHub Pages, a lab
server, ...) to show colleagues the results in the same interface, with the
3D viewer, contours, checks and report – no solver needed. Inputs are locked.
"""
import json, os, re, shutil, sys

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import pipeline, preview  # noqa: E402


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    cid, out = sys.argv[1], sys.argv[2]
    d = pipeline.case_dir(cid)
    st = pipeline.state(cid)
    os.makedirs(os.path.join(out, "vendor"), exist_ok=True)
    for f in ("app.js", "app.css"):
        shutil.copy2(os.path.join(APP, "static", f), os.path.join(out, f))
    for f in os.listdir(os.path.join(APP, "static", "vendor")):
        shutil.copy2(os.path.join(APP, "static", "vendor", f), os.path.join(out, "vendor", f))
    # every file the UI may request
    rels = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and re.match(r"^[\w./-]+\.(png|json|csv|html|md)$", o) and os.path.exists(os.path.join(d, o)):
            rels.add(o)
    walk(st["steps"])
    rels |= {"commands.sh", "report/report.html", "report/report.md"}
    for r in rels:
        src = os.path.join(d, r)
        if os.path.exists(src):
            os.makedirs(os.path.join(out, "data", os.path.dirname(r)), exist_ok=True)
            shutil.copy2(src, os.path.join(out, "data", r))
    json.dump(preview.history(os.path.join(d, "run")) or {}, open(os.path.join(out, "data", "history.json"), "w"))
    log = open(os.path.join(d, "log.txt"), errors="replace").read()
    log = re.sub(r"\x1b\[[0-9;]*m", "", log)
    if len(log) > 120_000:
        log = "… (log shortened for the static copy)\n" + log[-120_000:]
    demo = dict(base="data/", state=st, log=log,
                cases=[dict(id=cid, name=st["settings"]["name"], created=st["settings"].get("created"),
                            dim=st["derived"]["dim"])])
    body = open(os.path.join(APP, "static", "index.html")).read()
    body = body.replace('"/static/vendor/three.module.min.js"', '"./vendor/three.module.min.js"')
    body = body.replace('href="/static/app.css"', 'href="app.css"').replace('src="/static/app.js"', 'src="app.js"')
    boot = "<script>window.AEROSIM_DEMO=" + json.dumps(demo).replace("</", "<\\/") + ";</script>\n"
    body = body.replace('<script type="module"', boot + '<script type="module"')
    open(os.path.join(out, "index.html"), "w").write(body)
    print(f"wrote {out}/index.html with {len(rels)} result files")


if __name__ == "__main__":
    main()
