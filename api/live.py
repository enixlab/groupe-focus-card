"""
API Live — Preview player + IP/fingerprint blocking
====================================================
GET  /api/live                      → statut du live en cours
POST /api/live { action:"start", secret, title, stream_url }  → démarrer live
POST /api/live { action:"end",   secret }                     → terminer live
POST /api/live { action:"preview_request", fingerprint }      → demander accès preview
                → {"ok": true,  "token": "...", "stream_url": "...", "title": "..."}
                → {"ok": false, "reason": "no_live"|"already_used"|"ip_blocked"}

Logique IP blocking :
  - Chaque IP a droit à 1 preview de 3 minutes par tranche de 24h
  - Si la même IP tente à nouveau (même ou autre compte) → bloquée
  - Si une IP tente plus de 3 fois en 24h → bannie 7 jours
  - Le fingerprint (canvas+screen+timezone hash) sert de double vérification
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import json, os, sys, time, hashlib, hmac, base64, urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import _db
import push as _push

PUSH_SECRET      = os.environ.get("PUSH_SECRET", "MF2026FOCUS")
PREVIEW_DURATION = 300   # secondes (5 min)
BAN_THRESHOLD    = 3     # tentatives avant ban
BAN_DURATION     = 7 * 86400  # 7 jours en secondes


def _get_client_ip(handler):
    """Extraire l'IP réelle depuis les headers (Vercel passe X-Forwarded-For)."""
    xff = handler.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return handler.headers.get("X-Real-IP", "unknown")


def _ip_hash(ip: str) -> str:
    """Hasher l'IP pour ne pas la stocker en clair."""
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


def _check_access(ip: str, fingerprint: str, sessions: dict) -> dict:
    """
    Retourne {"allowed": True/False, "reason": str}
    """
    now        = time.time()
    ip_key     = _ip_hash(ip)
    fp_key     = hashlib.sha256(fingerprint.encode()).hexdigest()[:32] if fingerprint else ""

    # Vérifier le ban IP
    bans = sessions.get("bans", {})
    if ip_key in bans:
        ban_until = bans[ip_key]
        if now < ban_until:
            remaining = int((ban_until - now) / 3600)
            return {"allowed": False, "reason": "ip_blocked",
                    "message": f"Accès temporairement suspendu ({remaining}h restantes)."}
        else:
            del bans[ip_key]

    # Vérifier les tentatives IP dans les 24 dernières heures
    attempts = sessions.get("attempts", {})
    ip_attempts = [a for a in attempts.get(ip_key, []) if a > now - 86400]

    if len(ip_attempts) >= BAN_THRESHOLD:
        # Déclencher un ban
        if "bans" not in sessions:
            sessions["bans"] = {}
        sessions["bans"][ip_key] = now + BAN_DURATION
        return {"allowed": False, "reason": "ip_blocked",
                "message": "Trop de tentatives. Accès suspendu 7 jours."}

    # Vérifier si preview déjà utilisé aujourd'hui (1 par 24h par IP)
    previews = sessions.get("previews", {})
    if ip_key in previews:
        last_preview = previews[ip_key].get("ts", 0)
        if now - last_preview < 86400:
            return {"allowed": False, "reason": "already_used",
                    "message": "Aperçu déjà utilisé. Rejoins Focus pour accéder au live complet."}

    # Vérifier aussi par fingerprint (prévient le mode incognito / changement de compte)
    if fp_key and fp_key in previews:
        last_preview = previews[fp_key].get("ts", 0)
        if now - last_preview < 86400:
            return {"allowed": False, "reason": "already_used",
                    "message": "Aperçu déjà utilisé depuis ce navigateur."}

    return {"allowed": True, "ip_key": ip_key, "fp_key": fp_key}


def _record_attempt(ip_key: str, sessions: dict):
    now = time.time()
    if "attempts" not in sessions:
        sessions["attempts"] = {}
    if ip_key not in sessions["attempts"]:
        sessions["attempts"][ip_key] = []
    sessions["attempts"][ip_key].append(now)
    # Nettoyer les vieilles tentatives (> 24h)
    sessions["attempts"][ip_key] = [a for a in sessions["attempts"][ip_key] if a > now - 86400]


def _record_preview(ip_key: str, fp_key: str, sessions: dict):
    now = time.time()
    if "previews" not in sessions:
        sessions["previews"] = {}
    sessions["previews"][ip_key] = {"ts": now}
    if fp_key:
        sessions["previews"][fp_key] = {"ts": now}


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    # ── GET : statut live en cours + historique ─────────────────────────────
    def do_GET(self):
        qs = urlparse(self.path).query
        params = dict(p.split("=",1) for p in qs.split("&") if "=" in p) if qs else {}

        live, _ = _db.load("live.json", {"active": False})
        history_list, _ = _db.load("lives_history.json", [])

        self._respond({
            "current": live,
            "history": history_list[-20:]  # 20 derniers lives
        })

    # ── POST ────────────────────────────────────────────────────────────────
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            action = body.get("action", "")

            # ── Preview request (pas besoin de secret) ────────────────────
            if action == "preview_request":
                self._handle_preview_request(body)
                return

            # ── Actions admin (nécessite secret) ─────────────────────────
            if body.get("secret") != PUSH_SECRET:
                self._respond({"error": "forbidden"}, 403); return

            if action == "start":
                self._handle_start(body)
            elif action == "end":
                self._handle_end()
            elif action == "schedule":
                self._handle_schedule(body)
            elif action == "clean_sessions":
                self._handle_clean()
            else:
                self._respond({"error": "unknown action"}, 400)

        except Exception as e:
            self._respond({"error": str(e)}, 500)

    # ── Handlers ──────────────────────────────────────────────────────────
    def _handle_start(self, body):
        live_data = {
            "active":     True,
            "title":      body.get("title", "Live Mentalité Focus"),
            "host":       body.get("host", "Focus"),
            "stream_url": body.get("stream_url", ""),
            "started_at": time.time(),
        }
        live, sha = _db.load("live.json", {})
        _db.save("live.json", live_data, sha)

        # Ajouter à l'historique
        history, hsha = _db.load("lives_history.json", [])
        entry = {
            "id":    f"live_{int(time.time())}",
            "title": live_data["title"],
            "host":  live_data.get("host", "Focus"),
            "status": "live",
            "started_at": live_data["started_at"],
        }
        history.append(entry)
        _db.save("lives_history.json", history, hsha)

        # Envoyer push notification à tous les abonnés
        title = live_data["title"]
        push_result = _push.push_to_all(
            f"🔴 LIVE — {title}",
            f"{live_data['host']} est en direct maintenant !",
            "/"
        )

        self._respond({"ok": True, "live": live_data, "push": push_result})

    def _handle_end(self):
        live, sha = _db.load("live.json", {})
        live["active"]   = False
        live["ended_at"] = time.time()
        _db.save("live.json", live, sha)

        # Mettre à jour l'historique — marquer le dernier live comme ended
        history, hsha = _db.load("lives_history.json", [])
        if history:
            for entry in reversed(history):
                if entry.get("status") == "live":
                    entry["status"] = "ended"
                    entry["ended_at"] = live["ended_at"]
                    break
            _db.save("lives_history.json", history, hsha)

        self._respond({"ok": True})

    def _handle_schedule(self, body):
        """Programme un live futur."""
        history, hsha = _db.load("lives_history.json", [])
        scheduled_at = body.get("scheduled_at", time.time())
        entry = {
            "id": f"live_{int(scheduled_at)}",
            "title": body.get("title", "Live Focus"),
            "host": body.get("host", "Focus"),
            "status": "scheduled",
            "started_at": scheduled_at,
            "scheduled_at": scheduled_at,
        }
        history.append(entry)
        _db.save("lives_history.json", history, hsha)
        self._respond({"ok": True, "live": entry})

    def _handle_preview_request(self, body):
        ip          = _get_client_ip(self)
        fingerprint = body.get("fingerprint", "")

        # Charger le live en cours
        live, _ = _db.load("live.json", {"active": False})
        if not live.get("active"):
            self._respond({"ok": False, "reason": "no_live",
                           "message": "Aucun live en cours."})
            return

        # Charger les sessions
        sessions, sha = _db.load("live_sessions.json", {})

        ip_key = _ip_hash(ip)

        # Enregistrer la tentative
        _record_attempt(ip_key, sessions)

        # Vérifier l'accès
        result = _check_access(ip, fingerprint, sessions)

        if not result["allowed"]:
            _db.save("live_sessions.json", sessions, sha)
            self._respond({"ok": False,
                           "reason": result["reason"],
                           "message": result.get("message", "")})
            return

        # Accès autorisé — enregistrer le preview
        _record_preview(result["ip_key"], result["fp_key"], sessions)
        _db.save("live_sessions.json", sessions, sha)

        # Générer un token preview signé (valide PREVIEW_DURATION secondes)
        payload = base64.urlsafe_b64encode(
            json.dumps({
                "ip":      result["ip_key"],
                "ts":      int(time.time()),
                "expires": int(time.time()) + PREVIEW_DURATION
            }).encode()
        ).decode().rstrip("=")
        sig   = hmac.new(PUSH_SECRET.encode(), payload.encode(), __import__("hashlib").sha256).hexdigest()[:16]
        token = f"{payload}.{sig}"

        self._respond({
            "ok":         True,
            "token":      token,
            "stream_url": live.get("stream_url", ""),
            "title":      live.get("title", ""),
            "duration":   PREVIEW_DURATION,
        })

    def _handle_clean(self):
        """Nettoie les sessions expirées (> 24h)."""
        sessions, sha = _db.load("live_sessions.json", {})
        now = time.time()

        # Nettoyer previews > 24h
        previews = sessions.get("previews", {})
        sessions["previews"] = {k: v for k, v in previews.items()
                                 if now - v.get("ts", 0) < 86400}

        # Nettoyer bans expirés
        bans = sessions.get("bans", {})
        sessions["bans"] = {k: v for k, v in bans.items() if v > now}

        _db.save("live_sessions.json", sessions, sha)
        self._respond({"ok": True, "cleaned": True})

    # ── Util ──────────────────────────────────────────────────────────────
    def _respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *a): pass
