"""Start the hub.

    python run.py            HTTPS on :8443 with TLS 1.3 only + an HTTP :8080 listener that 308-redirects to HTTPS
    python run.py --http     plain HTTP on :8000 (local development without certificates)

Certificates: run scripts/gen_cert.sh (mkcert if available, otherwise OpenSSL) to create certs/cert.pem + key.pem.
"""
import argparse
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

HERE = Path(__file__).parent


def redirect_server(https_port: int, http_port: int) -> None:
    class Redirect(BaseHTTPRequestHandler):
        def _go(self):
            host = (self.headers.get("Host") or "localhost").split(":")[0]
            self.send_response(308)                             # 308 keeps the method and body
            self.send_header("Location", f"https://{host}:{https_port}{self.path}")
            self.send_header("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
            self.end_headers()
        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _go

        def log_message(self, *args):
            pass

    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", http_port), Redirect).serve_forever, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve plain HTTP on :8000 (dev only)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--workers-off", action="store_true", help="disable the notification outbox worker")
    args = ap.parse_args()

    if args.http:
        uvicorn.run("app.main:app", host=args.host, port=8000, proxy_headers=False)
        return

    cert, key = HERE / "certs/cert.pem", HERE / "certs/key.pem"
    if not cert.exists() or not key.exists():
        sys.exit("certs/cert.pem and certs/key.pem not found. Run scripts/gen_cert.sh first, or use --http.")
    redirect_server(8443, 8080)
    cfg = uvicorn.Config("app.main:app", host=args.host, port=8443, ssl_certfile=str(cert), ssl_keyfile=str(key))
    cfg.load()
    cfg.ssl.minimum_version = ssl.TLSVersion.TLSv1_3           # refuse TLS 1.2 and below
    print("Campus Events Hub on https://localhost:8443  (http://localhost:8080 redirects)")
    uvicorn.Server(cfg).run()


if __name__ == "__main__":
    main()
