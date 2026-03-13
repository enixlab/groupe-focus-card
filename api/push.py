"""
Push notifications vers TOUS les abonnés
GET  /api/push?secret=MF2026FOCUS&title=...&body=...&url=/&tier=ALL
POST /api/push { "secret":"MF2026FOCUS", "title":"...", "body":"...", "url":"/", "tier":"ALL" }
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, urllib.request, base64, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
import _db

PUSH_SECRET       = os.environ.get("PUSH_SECRET", "MF2026FOCUS")
VAPID_PUBLIC      = os.environ.get("VAPID_PUBLIC_KEY", "BCfanilVc5mqaRhRYXiWgt12EgPJ3WLvtrggqGey1KKwE_owSeIfMMgc3uhcikSx1QHUK_vAUlIUEfZ1k6TV0-E")
VAPID_PRIVATE_B64 = os.environ.get("VAPID_PRIVATE_KEY", "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg8AVD0P-ImvHuOVPgV-sRKnyVP-tQUkBo2x7haBcbcnKhRANCAAQn2p4pVXOZqmkYUWF4loLddhIDyd1i77a4IKhnstSisBP6MEniHzDIHN7oXIpEsdUB1Cv7wFJSFBH2dZOk1dPh")

TIERS_ORDER = {"MEMBRE":1,"ACTIF":2,"AVANCÉ":3,"EXPERT":4,"ÉLITE":5}

_last_push_error = ""

def send_vapid_push(subscription, payload):
    global _last_push_error
    try:
        from pywebpush import webpush
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_B64,
            vapid_claims={"sub": "mailto:enix.lab.ai@gmail.com"}
        )
        return True
    except Exception as e:
        _last_push_error = str(e)[:200]
        return False

def push_to_all(title, body, url="/", tier_filter="ALL"):
    subs, _ = _db.load("subscriptions.json", [])
    if tier_filter and tier_filter != "ALL":
        min_lvl = TIERS_ORDER.get(tier_filter, 1)
        subs    = [s for s in subs if TIERS_ORDER.get(s.get("tier","MEMBRE"),1) >= min_lvl]
    payload = {"title": title, "body": body, "url": url}
    results = {"sent": 0, "failed": 0, "total": len(subs)}
    for sub in subs:
        clean = {k:v for k,v in sub.items() if k in ["endpoint","keys","expirationTime"]}
        if send_vapid_push(clean, payload): results["sent"] += 1
        else: results["failed"] += 1
    if _last_push_error:
        results["last_error"] = _last_push_error
    return results

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        qs     = parse_qs(urlparse(self.path).query)
        secret = qs.get("secret",[""])[0]
        if secret != PUSH_SECRET:
            self.send_response(403); self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}'); return
        result = push_to_all(
            qs.get("title",["🔴 LIVE — Mentalité Focus"])[0],
            qs.get("body", ["Un live est en cours !"])[0],
            qs.get("url",  ["/"])[0],
            qs.get("tier", ["ALL"])[0]
        )
        self._respond(result)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            if body.get("secret") != PUSH_SECRET:
                self.send_response(403); self.end_headers(); return
            result = push_to_all(
                body.get("title","🔴 LIVE — Mentalité Focus"),
                body.get("body", "Un live commence maintenant !"),
                body.get("url",  "/"),
                body.get("tier", "ALL")
            )
            self._respond(result)
        except Exception as e:
            self._respond({"error": str(e)}, 500)

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
