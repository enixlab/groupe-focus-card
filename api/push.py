"""
Push notifications + Subscriptions
GET  /api/push?secret=MF2026FOCUS&title=...&body=...&url=/&tier=ALL  → envoyer push
POST /api/push { "secret":"...", "title":"...", "body":"...", "url":"/", "tier":"ALL" } → envoyer push
GET  /api/subscribe → total abonnés
POST /api/subscribe { "subscription":{...}, "discord_name":"...", "tier":"..." } → s'abonner
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time

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

def _handle_subscribe(handler, body):
    sub = body.get("subscription")
    if not sub:
        _respond(handler, {"error": "no subscription"}, 400); return
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
    _respond(handler, {"ok": True, "total": len(subs)}, 201)

def _respond(handler, data, code=200):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers(); handler.wfile.write(body)

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        # GET /api/subscribe → total abonnés
        if path.rstrip("/").endswith("/subscribe"):
            subs, _ = _db.load("subscriptions.json", [])
            _respond(self, {"total": len(subs)}); return

        # GET /api/push → envoyer push (nécessite secret)
        qs     = parse_qs(urlparse(self.path).query)
        secret = qs.get("secret",[""])[0]
        if secret != PUSH_SECRET:
            _respond(self, {"error": "forbidden"}, 403); return
        result = push_to_all(
            qs.get("title",["\U0001f534 LIVE — Mentalité Focus"])[0],
            qs.get("body", ["Un live est en cours !"])[0],
            qs.get("url",  ["/"])[0],
            qs.get("tier", ["ALL"])[0]
        )
        _respond(self, result)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            path   = urlparse(self.path).path

            # POST /api/subscribe → inscription push
            if path.rstrip("/").endswith("/subscribe"):
                _handle_subscribe(self, body); return

            # POST /api/push → envoyer push
            if body.get("secret") != PUSH_SECRET:
                _respond(self, {"error": "forbidden"}, 403); return
            result = push_to_all(
                body.get("title","\U0001f534 LIVE — Mentalité Focus"),
                body.get("body", "Un live commence maintenant !"),
                body.get("url",  "/"),
                body.get("tier", "ALL")
            )
            _respond(self, result)
        except Exception as e:
            _respond(self, {"error": str(e)}, 500)

    def log_message(self, *a): pass
