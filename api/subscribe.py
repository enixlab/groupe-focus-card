"""
POST /api/subscribe  { "subscription": {...}, "discord_name": "...", "tier": "..." }
GET  /api/subscribe  → total abonnés
"""
from http.server import BaseHTTPRequestHandler
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import _db

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        subs, _ = _db.load("subscriptions.json", [])
        self._respond({"total": len(subs)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            sub    = body.get("subscription")
            if not sub: raise ValueError("no subscription")

            subs, sha = _db.load("subscriptions.json", [])
            ep   = sub.get("endpoint", "")
            subs = [s for s in subs if s.get("endpoint") != ep]
            subs.append({
                **sub,
                "discord_name": body.get("discord_name", ""),
                "discord_id":   body.get("discord_id", ""),
                "tier":         body.get("tier", "MEMBRE"),
                "ts":           time.time()
            })
            _db.save("subscriptions.json", subs, sha)
            self._respond({"ok": True, "total": len(subs)}, 201)
        except Exception as e:
            self._respond({"error": str(e)}, 400)

    def _respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *a): pass
