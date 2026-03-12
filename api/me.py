"""
GET  /api/me?token=xxx  → profil membre
POST /api/me { "token":"...", "pts":x, ... } → sync profil
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time, hashlib, hmac, base64

sys.path.insert(0, os.path.dirname(__file__))
import _db

JWT_SECRET = os.environ.get("JWT_SECRET","MF2026FOCUS_SECRET")
TIERS = [
    {"name":"MEMBRE","min":0},{"name":"ACTIF","min":10},
    {"name":"AVANCÉ","min":30},{"name":"EXPERT","min":60},{"name":"ÉLITE","min":100}
]

def get_tier(pts):
    t = TIERS[0]
    for tier in TIERS:
        if pts >= tier["min"]: t = tier
    return t["name"]

def verify_token(token):
    try:
        payload, sig = token.rsplit(".",1)
        exp = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, exp): return None
        return json.loads(base64.urlsafe_b64decode(payload+"=="))
    except: return None

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs    = parse_qs(urlparse(self.path).query)
        token = qs.get("token",[""])[0]
        data  = verify_token(token)
        if not data: self._respond({"error":"invalid token"},401); return
        try:
            members, _ = _db.load("members.json",{})
            member     = members.get(data["discord_id"])
            if not member: self._respond({"error":"not found"},404); return
            member["tier"] = get_tier(member.get("pts",0))
            self._respond(member)
        except Exception as e:
            self._respond({"error":str(e)},500)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length",0))
            body   = json.loads(self.rfile.read(length))

            # Connexion par pseudo Discord (sans OAuth2)
            if body.get("action") == "login_name":
                name     = body.get("discord_name","").strip()
                if not name: self._respond({"error":"name required"},400); return
                did      = "manual_" + hashlib.md5(name.encode()).hexdigest()[:12]
                members, sha = _db.load("members.json",{})
                if did not in members:
                    members[did] = {
                        "discord_id":   did,
                        "discord_name": name,
                        "discord_avatar": "",
                        "pts":0,"cyclePoints":0,"totalCycles":0,
                        "watchedLives":[],"earned":[],"tier":"MEMBRE",
                        "joined_at":time.time(),"last_seen":time.time()
                    }
                else:
                    members[did]["last_seen"] = time.time()
                members[did]["tier"] = get_tier(members[did].get("pts",0))
                _db.save("members.json", members, sha)
                # Générer token
                payload = base64.urlsafe_b64encode(json.dumps({"discord_id":did,"discord_name":name,"ts":int(time.time())}).encode()).decode().rstrip("=")
                sig     = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
                token   = f"{payload}.{sig}"
                self._respond({"ok":True,"token":token,"member":members[did]}); return

            # Sync profil
            token  = body.get("token","")
            data   = verify_token(token)
            if not data: self._respond({"error":"invalid token"},401); return
            members, sha = _db.load("members.json",{})
            did = data["discord_id"]
            if did not in members: self._respond({"error":"not found"},404); return
            m = members[did]
            for f in ["pts","cyclePoints","totalCycles","watchedLives","earned","contested"]:
                if f in body: m[f] = body[f]
            m["last_seen"] = time.time()
            m["tier"]      = get_tier(m.get("pts",0))
            members[did]   = m
            _db.save("members.json", members, sha)
            self._respond({"ok":True,"member":m})
        except Exception as e:
            self._respond({"error":str(e)},500)

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
