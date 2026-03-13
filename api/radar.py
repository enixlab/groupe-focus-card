"""
Radar — Membres Focus à proximité (10 km)
GET  /api/radar?lat=...&lng=...&radius=10  → liste des membres proches
POST /api/radar { action: "register"|"unregister", discord_id, name, avatar, tier, lat, lng }
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time, math

sys.path.insert(0, os.path.dirname(__file__))
import _db

RADAR_FILE = "radar_positions.json"
MAX_AGE = 3600  # positions expirent après 1h d'inactivité


def haversine(lat1, lng1, lat2, lng2):
    """Distance en km entre deux points GPS."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        try:
            lat = float(qs.get("lat", ["0"])[0])
            lng = float(qs.get("lng", ["0"])[0])
            radius = float(qs.get("radius", ["10"])[0])
            exclude = qs.get("exclude", [""])[0]
        except (ValueError, IndexError):
            self._respond({"error": "invalid params"}, 400)
            return

        positions, _ = _db.load(RADAR_FILE, [])
        now = time.time()

        # Filtrer les positions expirées et calculer la distance
        nearby = []
        for p in positions:
            if exclude and p.get("discord_id") == exclude:
                continue
            age = now - p.get("ts", 0)
            if age > MAX_AGE:
                continue
            dist = haversine(lat, lng, p.get("lat", 0), p.get("lng", 0))
            if dist <= radius:
                nearby.append({
                    "discord_id": p.get("discord_id", ""),
                    "name": p.get("name", "Membre"),
                    "avatar": p.get("avatar", ""),
                    "tier": p.get("tier", "MEMBRE"),
                    "distance_km": round(dist, 2)
                })

        # Trier par distance
        nearby.sort(key=lambda x: x["distance_km"])

        self._respond({"members": nearby, "count": len(nearby)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            action = body.get("action", "")

            positions, sha = _db.load(RADAR_FILE, [])
            now = time.time()

            # Nettoyer les positions expirées
            positions = [p for p in positions if now - p.get("ts", 0) < MAX_AGE]

            if action == "register":
                discord_id = body.get("discord_id", "")
                if not discord_id:
                    self._respond({"error": "discord_id required"}, 400)
                    return

                # Mettre à jour ou ajouter
                positions = [p for p in positions if p.get("discord_id") != discord_id]
                positions.append({
                    "discord_id": discord_id,
                    "name": body.get("name", "Membre"),
                    "avatar": body.get("avatar", ""),
                    "tier": body.get("tier", "MEMBRE"),
                    "lat": float(body.get("lat", 0)),
                    "lng": float(body.get("lng", 0)),
                    "ts": now
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
