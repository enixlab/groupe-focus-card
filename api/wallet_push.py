"""
Apple Wallet Push Notifications + Registration API
=====================================================
Endpoints requis par Apple Wallet (webServiceURL) :
  POST   /api/wallet_push?register=1  → device enregistre le pass
  DELETE /api/wallet_push?register=1  → device desenregistre le pass
  GET    /api/wallet_push?passes=1    → liste des passes mis a jour
  GET    /api/wallet_push?pass=1      → telecharge le pass mis a jour

Admin :
  POST   /api/wallet_push { "action":"notify", "secret":"..." } → push a tous les devices
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time, ssl, struct, hashlib

sys.path.insert(0, os.path.dirname(__file__))
import _db

PUSH_SECRET = os.environ.get("PUSH_SECRET", "MF2026FOCUS")
PASS_TYPE_ID = "pass.com.mentalitefocus.loyalty"
TEAM_ID = "TRX9J5U7L6"

CERTS_DIR = os.path.join(os.path.dirname(__file__), "certs")


def _load_file(name):
    p = os.path.join(CERTS_DIR, name)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    return b""


def send_apns_push(device_token, cert_pem, key_pem):
    """Envoie une push notification vide via APNs (HTTP/2) pour forcer le Wallet a re-telecharger le pass."""
    import http.client

    # APNs production endpoint
    conn = http.client.HTTPSConnection(
        "api.push.apple.com", 443,
        context=_make_ssl_context(cert_pem, key_pem)
    )

    headers = {
        "apns-topic": PASS_TYPE_ID,
        "apns-push-type": "background",
        "apns-priority": "5",
    }

    # Apple Wallet push = payload vide JSON
    payload = json.dumps({}).encode()

    try:
        conn.request("POST", f"/3/device/{device_token}", body=payload, headers=headers)
        resp = conn.getresponse()
        result = {"status": resp.status, "reason": resp.read().decode()}
        conn.close()
        return result
    except Exception as e:
        return {"status": 0, "reason": str(e)}


def _make_ssl_context(cert_pem, key_pem):
    """Cree un contexte SSL avec le certificat et la cle du pass."""
    import tempfile
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Ecrire cert et key dans des fichiers temporaires
    cert_f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    cert_f.write(cert_pem)
    cert_f.close()

    key_f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    key_f.write(key_pem)
    key_f.close()

    ctx.load_cert_chain(cert_f.name, key_f.name)

    os.unlink(cert_f.name)
    os.unlink(key_f.name)

    return ctx


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── GET : Apple Wallet appelle pour recuperer les passes mis a jour ──
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        path = urlparse(self.path).path

        # GET /api/wallet_push?passes=1 → serialNumbers des passes modifies
        if qs.get("passes"):
            devices, _ = _db.load("wallet_devices.json", {})
            self._respond({
                "serialNumbers": list(set(
                    d.get("serial", "") for d in devices.values() if d.get("serial")
                )),
                "lastUpdated": str(int(time.time()))
            })
            return

        # GET /api/wallet_push?pass=1&serial=xxx → re-telecharge le pass
        if qs.get("pass"):
            serial = qs.get("serial", [""])[0]
            # Importer pass builder
            from importlib import import_module
            pass_mod = import_module("pass")
            # Extraire infos du serial: FOCUS-NAME-PTS-CYCLE
            parts = serial.replace("FOCUS-", "").rsplit("-", 2)
            name = parts[0] if len(parts) >= 1 else "MEMBRE"
            pts = parts[1] if len(parts) >= 2 else "0"
            cycle = parts[2] if len(parts) >= 3 else "1"
            level = "MEMBRE"
            pkpass = pass_mod.create_pkpass(name, pts, cycle, level)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.pkpass")
            self.send_header("Content-Length", str(len(pkpass)))
            self.end_headers()
            self.wfile.write(pkpass)
            return

        # GET /api/wallet_push?status=1 → stats
        if qs.get("status"):
            devices, _ = _db.load("wallet_devices.json", {})
            self._respond({"devices": len(devices), "ok": True})
            return

        self._respond({"error": "unknown"}, 400)

    # ── POST : enregistrement device OU admin push ──
    def do_POST(self):
        qs = parse_qs(urlparse(self.path).query)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # ── Device registration (Apple Wallet appelle ca) ──
        if qs.get("register"):
            device_token = body.get("deviceLibraryIdentifier", "")
            push_token = body.get("pushToken", "")
            serial = body.get("serialNumber", "")

            if not push_token:
                self._respond({"error": "missing pushToken"}, 400)
                return

            devices, sha = _db.load("wallet_devices.json", {})
            devices[device_token] = {
                "push_token": push_token,
                "serial": serial,
                "registered_at": time.time()
            }
            _db.save("wallet_devices.json", devices, sha)
            self._respond({"ok": True}, 201)
            return

        # ── Admin: envoyer push a tous les devices ──
        if body.get("action") == "notify":
            if body.get("secret") != PUSH_SECRET:
                self._respond({"error": "forbidden"}, 403)
                return

            cert_pem = _load_file("certificate.pem")
            key_pem = _load_file("pass_private.key")

            if not cert_pem or not key_pem:
                self._respond({"error": "no cert"}, 500)
                return

            devices, _ = _db.load("wallet_devices.json", {})
            results = {"sent": 0, "failed": 0, "total": len(devices)}

            for did, dinfo in devices.items():
                push_token = dinfo.get("push_token", "")
                if not push_token:
                    results["failed"] += 1
                    continue
                r = send_apns_push(push_token, cert_pem, key_pem)
                if r["status"] == 200:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
                    results["last_error"] = r["reason"]

            self._respond(results)
            return

        self._respond({"error": "unknown action"}, 400)

    # ── DELETE : device desenregistre ──
    def do_DELETE(self):
        qs = parse_qs(urlparse(self.path).query)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        device_token = body.get("deviceLibraryIdentifier", "")
        if device_token:
            devices, sha = _db.load("wallet_devices.json", {})
            if device_token in devices:
                del devices[device_token]
                _db.save("wallet_devices.json", devices, sha)
            self._respond({"ok": True})
        else:
            self._respond({"error": "missing device"}, 400)

    def _respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, *a):
        pass
