"""
Apple Wallet Web Service API
==============================
Apple Wallet appelle ces URLs automatiquement :

  POST   /api/wallet_push/v1/devices/{deviceID}/registrations/{passTypeID}/{serial}
  DELETE /api/wallet_push/v1/devices/{deviceID}/registrations/{passTypeID}/{serial}
  GET    /api/wallet_push/v1/devices/{deviceID}/registrations/{passTypeID}
  GET    /api/wallet_push/v1/passes/{passTypeID}/{serial}
  GET    /api/wallet_push/v1/log

Admin :
  POST   /api/wallet_push  { "action":"notify", "secret":"..." }
  GET    /api/wallet_push?status=1
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys, time, ssl, hashlib, re

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


def send_apns_push(push_token, cert_pem, key_pem):
    """Push APNs vide pour forcer Wallet a re-telecharger le pass."""
    import http.client, tempfile

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    cert_f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    cert_f.write(cert_pem)
    cert_f.close()
    key_f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    key_f.write(key_pem)
    key_f.close()

    ctx.load_cert_chain(cert_f.name, key_f.name)
    os.unlink(cert_f.name)
    os.unlink(key_f.name)

    try:
        conn = http.client.HTTPSConnection("api.push.apple.com", 443, context=ctx)
        conn.request("POST", f"/3/device/{push_token}",
                     body=b"{}",
                     headers={
                         "apns-topic": PASS_TYPE_ID,
                         "apns-push-type": "background",
                         "apns-priority": "5",
                     })
        resp = conn.getresponse()
        result = {"status": resp.status, "reason": resp.read().decode()}
        conn.close()
        return result
    except Exception as e:
        return {"status": 0, "reason": str(e)}


def _parse_path(path):
    """Parse le path pour extraire l'action Apple Wallet."""
    # /api/wallet_push/v1/devices/{deviceID}/registrations/{passTypeID}/{serial}
    m = re.match(r'.*/v1/devices/([^/]+)/registrations/([^/]+)/([^/]+)', path)
    if m:
        return {"action": "register", "device_id": m.group(1), "pass_type": m.group(2), "serial": m.group(3)}

    # /api/wallet_push/v1/devices/{deviceID}/registrations/{passTypeID}
    m = re.match(r'.*/v1/devices/([^/]+)/registrations/([^/]+)$', path)
    if m:
        return {"action": "serials", "device_id": m.group(1), "pass_type": m.group(2)}

    # /api/wallet_push/v1/passes/{passTypeID}/{serial}
    m = re.match(r'.*/v1/passes/([^/]+)/([^/]+)', path)
    if m:
        return {"action": "latest", "pass_type": m.group(1), "serial": m.group(2)}

    # /api/wallet_push/v1/log
    if "/v1/log" in path:
        return {"action": "log"}

    return {"action": "admin"}


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        info = _parse_path(path)

        # ── Admin: status ──
        if info["action"] == "admin" and qs.get("status"):
            devices, _ = _db.load("wallet_devices.json", {})
            self._respond({"devices": len(devices), "ok": True})
            return

        # ── GET serials for device ──
        if info["action"] == "serials":
            devices, _ = _db.load("wallet_devices.json", {})
            device_id = info["device_id"]
            serials = []
            if device_id in devices:
                s = devices[device_id].get("serial", "")
                if s:
                    serials.append(s)
            if serials:
                self._respond({
                    "serialNumbers": serials,
                    "lastUpdated": str(int(time.time()))
                })
            else:
                self.send_response(204)
                self.end_headers()
            return

        # ── GET latest pass ──
        if info["action"] == "latest":
            serial = info["serial"]
            from importlib import import_module
            pass_mod = import_module("pass")
            parts = serial.replace("FOCUS-", "").rsplit("-", 2)
            name = parts[0] if len(parts) >= 1 else "MEMBRE"
            pts = parts[1] if len(parts) >= 2 else "0"
            cycle = parts[2] if len(parts) >= 3 else "1"
            try:
                pkpass = pass_mod.create_pkpass(name, pts, cycle, "MEMBRE")
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.pkpass")
                self.send_header("Content-Length", str(len(pkpass)))
                self.end_headers()
                self.wfile.write(pkpass)
            except Exception as e:
                self._respond({"error": str(e)}, 500)
            return

        self._respond({"ok": True})

    def do_POST(self):
        path = urlparse(self.path).path
        info = _parse_path(path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}

        # ── Apple Wallet: register device ──
        if info["action"] == "register":
            device_id = info["device_id"]
            serial = info["serial"]
            push_token = body.get("pushToken", "")

            devices, sha = _db.load("wallet_devices.json", {})
            devices[device_id] = {
                "push_token": push_token,
                "serial": serial,
                "registered_at": time.time()
            }
            _db.save("wallet_devices.json", devices, sha)

            # 201 = nouveau, 200 = deja existant
            self.send_response(201)
            self.end_headers()
            return

        # ── Apple Wallet: log ──
        if info["action"] == "log":
            # Apple envoie des logs, on les ignore
            self.send_response(200)
            self.end_headers()
            return

        # ── Admin: notify all devices ──
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
                pt = dinfo.get("push_token", "")
                if not pt:
                    results["failed"] += 1
                    continue
                r = send_apns_push(pt, cert_pem, key_pem)
                if r["status"] == 200:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
                    results["last_error"] = r

            self._respond(results)
            return

        self._respond({"ok": True})

    def do_DELETE(self):
        path = urlparse(self.path).path
        info = _parse_path(path)

        if info["action"] == "register":
            device_id = info["device_id"]
            devices, sha = _db.load("wallet_devices.json", {})
            if device_id in devices:
                del devices[device_id]
                _db.save("wallet_devices.json", devices, sha)
            self.send_response(200)
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()

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
