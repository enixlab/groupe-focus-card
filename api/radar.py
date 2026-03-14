"""
Radar — Membres Focus actifs (connectés dans la dernière heure)
GET  /api/radar?exclude=discord_id  → tous les membres actifs
POST /api/radar { action: "register"|"unregister"|"ping", discord_id, name, avatar, tier }
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
import _db

RADAR_FILE = "radar_positions.json"
MAX_AGE = 3600  # actif = connecté dans la dernière heure


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        exclude = qs.get("exclude", [""])[0]

        positions, _ = _db.load(RADAR_FILE, [])
        now = time.time()

        active = []
        for p in positions:
            if exclude and p.get("discord_id") == exclude:
                continue
            age = now - p.get("ts", 0)
            if age > MAX_AGE:
                continue
            active.append({
                "discord_id": p.get("discord_id", ""),
                "name":       p.get("name", "Membre"),
                "avatar":     p.get("avatar", ""),
                "tier":       p.get("tier", "MEMBRE"),
                "online":     age < 300  # vert si actif < 5 min
            })

        # Trier : online d'abord
        active.sort(key=lambda x: (0 if x["online"] else 1, x["name"]))
        self._respond({"members": active, "count": len(active)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            action = body.get("action", "")

            positions, sha = _db.load(RADAR_FILE, [])
            now = time.time()
            positions = [p for p in positions if now - p.get("ts", 0) < MAX_AGE]

            if action in ("register", "ping"):
                discord_id = body.get("discord_id", "")
                if not discord_id:
                    self._respond({"error": "discord_id required"}, 400); return
                positions = [p for p in positions if p.get("discord_id") != discord_id]
                positions.append({
                    "discord_id": discord_id,
                    "name":   body.get("name", "Membre"),
                    "avatar": body.get("avatar", ""),
                    "tier":   body.get("tier", "MEMBRE"),
                    "ts":     now
                })
                _db.save(RADAR_FILE, positions, sha)
                self._respond({"ok": True, "active": len(positions)})

            elif action == "unregister":
                discord_id = body.get("discord_id", "")
                positions = [p for p in positions if p.get("discord_id") != discord_id]
                _db.save(RADAR_FILE, positions, sha)
                self._respond({"ok": True})
            else:
                self._respond({"error": "invalid action"}, 400)

        except Exception as e:
            self._respond({"error": str(e)[:200]}, 500)

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
