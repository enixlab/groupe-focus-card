"""
Chat — Messages entre membres actifs
GET  /api/chat?since=timestamp  → messages récents
POST /api/chat { discord_id, name, avatar, tier, message }
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
import _db

CHAT_FILE = "chat_messages.json"
MAX_MESSAGES = 200
MAX_AGE = 86400  # 24h


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        since = float(qs.get("since", ["0"])[0])

        messages, _ = _db.load(CHAT_FILE, [])
        now = time.time()

        # Filtrer messages récents
        recent = [m for m in messages if m.get("ts", 0) > since and now - m.get("ts", 0) < MAX_AGE]
        self._respond({"messages": recent})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            discord_id = body.get("discord_id", "")
            message    = body.get("message", "").strip()[:300]

            if not discord_id or not message:
                self._respond({"error": "discord_id and message required"}, 400); return

            messages, sha = _db.load(CHAT_FILE, [])
            now = time.time()

            # Nettoyer anciens messages
            messages = [m for m in messages if now - m.get("ts", 0) < MAX_AGE]

            # Anti-spam : 1 message / 3 secondes par user
            recent_user = [m for m in messages if m.get("discord_id") == discord_id and now - m.get("ts", 0) < 3]
            if recent_user:
                self._respond({"error": "slow down"}, 429); return

            messages.append({
                "id":         str(int(now * 1000)),
                "discord_id": discord_id,
                "name":       body.get("name", "Membre")[:30],
                "avatar":     body.get("avatar", ""),
                "tier":       body.get("tier", "MEMBRE"),
                "message":    message,
                "ts":         now
            })

            # Garder seulement les derniers MAX_MESSAGES
            messages = messages[-MAX_MESSAGES:]
            _db.save(CHAT_FILE, messages, sha)
            self._respond({"ok": True, "ts": now})

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
