#!/usr/bin/env python3
"""AeroSim Workbench – local web server.

    python server.py [--port 8050] [--host 127.0.0.1]

then open http://localhost:8050 . Standard library only (plus the skill's
numpy / gmsh / meshio stack used by the pipeline).
"""
import argparse, json, mimetypes, os, sys, traceback, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import pipeline  # noqa: E402
import preview   # noqa: E402

STATIC = os.path.join(APP, "static")
MAX_UPLOAD = 300 * 1024 * 1024


class H(BaseHTTPRequestHandler):
    server_version = "AeroSim/1.0"

    def log_message(self, fmt, *a):
        if "/api/" in (a[0] if a else "") and " 200 " not in fmt % a:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))

    # ------------------------------------------------------------ helpers
    def send_json(self, obj, code=200):
        b = json.dumps(obj, default=float).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def send_file(self, path, download=False):
        if not os.path.isfile(path):
            return self.send_json(dict(error="not found"), 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith((".md", ".cfg", ".sh", ".dat", ".inp", ".su2", ".log")):
            ctype = "text/plain; charset=utf-8"
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-cache")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("upload too large")
        return self.rfile.read(n) if n else b""

    def route(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/") if p]
        return parts, q

    # ------------------------------------------------------------ GET
    def do_GET(self):
        try:
            parts, q = self.route()
            if not parts:
                return self.send_file(os.path.join(STATIC, "index.html"))
            if parts[0] == "static":
                p = os.path.realpath(os.path.join(STATIC, *parts[1:]))
                if not p.startswith(STATIC):
                    return self.send_json(dict(error="bad path"), 400)
                return self.send_file(p)
            if parts[0] == "files" and len(parts) >= 3:          # /files/<case>/<relpath>
                d = pipeline.case_dir(parts[1])
                p = os.path.realpath(os.path.join(d, *parts[2:]))
                if not p.startswith(d + os.sep):
                    return self.send_json(dict(error="bad path"), 400)
                return self.send_file(p, download=q.get("dl") == "1")
            if parts[:2] == ["api", "cases"]:
                return self.send_json(pipeline.list_cases())
            if parts[:2] == ["api", "defaults"]:
                return self.send_json(dict(defaults=pipeline.DEFAULTS, materials=pipeline.MATERIALS))
            if parts[0] == "api" and parts[1] == "case" and len(parts) >= 3:
                cid = parts[2]
                what = parts[3] if len(parts) > 3 else "state"
                if what == "state":
                    return self.send_json(pipeline.state(cid))
                if what == "log":
                    return self.send_json(pipeline.log_tail(cid, q.get("from", 0)))
                if what == "history":
                    d = pipeline.case_dir(cid)
                    return self.send_json(preview.history(os.path.join(d, "run")) or {})
                if what == "derive":
                    d, c = pipeline.load(cid)
                    dv = pipeline.derive(c, d)
                    return self.send_json(dv)
            self.send_json(dict(error="not found"), 404)
        except KeyError:
            self.send_json(dict(error="case not found"), 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            self.send_json(dict(error=str(e)), 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        try:
            parts, q = self.route()
            if parts[:2] == ["api", "cases"]:
                b = json.loads(self.body() or b"{}")
                cid = pipeline.create_case(b.get("name") or "New case", b.get("template"))
                return self.send_json(dict(id=cid))
            if parts[0] == "api" and parts[1] == "case" and len(parts) >= 4:
                cid, what = parts[2], parts[3]
                if what == "settings":
                    c = pipeline.save_settings(cid, json.loads(self.body() or b"{}"))
                    return self.send_json(dict(ok=True, settings=c))
                if what == "upload":
                    rel = pipeline.save_upload(cid, q.get("name", "upload.step"), self.body())
                    return self.send_json(dict(ok=True, file=rel))
                if what == "run":
                    b = json.loads(self.body() or b"{}")
                    steps = pipeline.run_steps(cid, upto=b.get("upto"), only=b.get("only"))
                    return self.send_json(dict(ok=True, steps=steps))
                if what == "stop":
                    pipeline.stop(cid)
                    return self.send_json(dict(ok=True))
                if what == "delete":
                    pipeline.delete_case(cid)
                    return self.send_json(dict(ok=True))
            self.send_json(dict(error="not found"), 404)
        except KeyError:
            self.send_json(dict(error="case not found"), 404)
        except Exception as e:
            traceback.print_exc()
            self.send_json(dict(error=str(e)), 400)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to share on your network")
    a = ap.parse_args()
    os.makedirs(pipeline.WORK, exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"AeroSim Workbench running:  http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}")
    print(f"cases stored in {pipeline.WORK}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
