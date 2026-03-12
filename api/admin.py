"""
Panel Admin — Offres, Concours, Stats, Push
GET  /api/admin?action=offers|contests          → public
GET  /api/admin?secret=MF2026FOCUS&action=stats → admin
POST /api/admin { "secret":"MF2026FOCUS", "action":"add_offer|add_contest|delete_offer|delete_contest" }
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
import _db

PUSH_SECRET = os.environ.get("PUSH_SECRET", "MF2026FOCUS")

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs     = parse_qs(urlparse(self.path).query)
        action = qs.get("action", ["stats"])[0]
        secret = qs.get("secret", [""])[0]
        now    = time.time()

        if action == "offers":
            offers, _ = _db.load("offers.json", [])
            active    = [o for o in offers if o.get("active") and (not o.get("expires_at") or o["expires_at"] > now)]
            self._respond(active); return

        if action == "contests":
            contests, _ = _db.load("contests.json", [])
            active      = [c for c in contests if c.get("active") and (not c.get("ends_at") or c["ends_at"] > now)]
            self._respond(active); return

        if secret != PUSH_SECRET:
            self._respond({"error":"forbidden"}, 403); return

        if action == "stats":
            subs, _     = _db.load("subscriptions.json", [])
            offers, _   = _db.load("offers.json", [])
            contests, _ = _db.load("contests.json", [])
            members, _  = _db.load("members.json", {})
            tiers = {}
            for s in subs:
                t = s.get("tier","MEMBRE"); tiers[t] = tiers.get(t,0)+1
            self._respond({
                "total_subscribers":  len(subs),
                "total_members":      len(members),
                "tiers":              tiers,
                "active_offers":      len([o for o in offers if o.get("active")]),
                "active_contests":    len([c for c in contests if c.get("active")])
            })

        if action == "all_offers":
            offers, _ = _db.load("offers.json", [])
            self._respond(offers)

        if action == "all_contests":
            contests, _ = _db.load("contests.json", [])
            self._respond(contests)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length",0))
            body   = json.loads(self.rfile.read(length))
            if body.get("secret") != PUSH_SECRET:
                self._respond({"error":"forbidden"}, 403); return
            action = body.get("action","")

            if action == "add_offer":
                offers, sha = _db.load("offers.json", [])
                offer = {
                    "id":          str(int(time.time())),
                    "title":       body.get("title","Offre Flash"),
                    "description": body.get("description",""),
                    "emoji":       body.get("emoji","🎁"),
                    "code":        body.get("code",""),
                    "link":        body.get("link",""),
                    "expires_at":  time.time() + body.get("hours",24)*3600,
                    "active":      True,
                    "created_at":  time.time()
                }
                offers.append(offer)
                _db.save("offers.json", offers, sha)
                self._respond({"ok":True,"offer":offer})

            elif action == "add_contest":
                contests, sha = _db.load("contests.json", [])
                contest = {
                    "id":          str(int(time.time())),
                    "title":       body.get("title","Concours"),
                    "description": body.get("description",""),
                    "emoji":       body.get("emoji","🏆"),
                    "prize":       body.get("prize",""),
                    "how_to":      body.get("how_to",""),
                    "ends_at":     time.time() + body.get("days",7)*86400,
                    "active":      True,
                    "created_at":  time.time()
                }
                contests.append(contest)
                _db.save("contests.json", contests, sha)
                self._respond({"ok":True,"contest":contest})

            elif action == "delete_offer":
                offers, sha = _db.load("offers.json", [])
                offers = [o for o in offers if o.get("id") != body.get("id")]
                _db.save("offers.json", offers, sha)
                self._respond({"ok":True})

            elif action == "delete_contest":
                contests, sha = _db.load("contests.json", [])
                contests = [c for c in contests if c.get("id") != body.get("id")]
                _db.save("contests.json", contests, sha)
                self._respond({"ok":True})

            else:
                self._respond({"error":"unknown action"}, 400)

        except Exception as e:
            self._respond({"error": str(e)}, 500)

    def _respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")

    def log_message(self, *a): pass
