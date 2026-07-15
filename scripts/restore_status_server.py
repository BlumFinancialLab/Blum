from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HTML = b"""<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BLUM startup</title></head>
  <body style="margin:0;background:#080b0e;color:#e8eef2;font-family:system-ui,sans-serif;display:grid;min-height:100vh;place-items:center">
    <main style="max-width:620px;padding:32px"><p style="color:#72d6a3;font-weight:700">BLUM | TRADER BRAIN</p><h1>BLUM is restoring its learning memory</h1><p style="color:#9aa7b2;line-height:1.6">The service is healthy but not ready. The API starts automatically after persisted market history is restored. No learning data is being discarded.</p></main>
  </body>
</html>
"""


class RestoreStatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path.split("?", 1)[0] in {"/health", "/startup/status"}:
            payload = json.dumps(
                {
                    "status": "restoring",
                    "healthy": True,
                    "api_ready": False,
                    "ui_ready": True,
                    "current_stage": "database_restore",
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    ThreadingHTTPServer(("0.0.0.0", port), RestoreStatusHandler).serve_forever()
