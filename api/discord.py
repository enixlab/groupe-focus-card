"""
Discord OAuth2 — Connexion membre (échange côté serveur avec proxy POST)
GET  /api/discord          → redirige vers Discord OAuth2
GET  /api/discord?code=xxx → callback → échange code → redirige avec token
POST /api/discord          → proxy token exchange (évite blocage IP Vercel)
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import json, urllib.request, urllib.error, os, hashlib, hmac, time, base64

DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "1481723128588669040")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "QqP4hS1etJcrVI-mvsBIvQ6qBJMRn0sa")
DISCORD_GUILD_ID      = os.environ.get("DISCORD_GUILD_ID", "1481745584602742847")
JWT_SECRET            = os.environ.get("JWT_SECRET", "MF2026FOCUS_SECRET")
APP_URL               = os.environ.get("APP_URL", "https://groupe-focus-card.vercel.app")
REDIRECT_URI          = APP_URL + "/api/discord"

# ── JWT simple (HMAC-SHA256) ──────────────────────────────────────────────────
def make_token(data):
    payload   = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    sig       = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"

def verify_token(token):
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected): return None
        return json.loads(base64.urlsafe_b64decode(payload + "=="))
    except: return None

# ── Discord API ───────────────────────────────────────────────────────────────
def discord_exchange_code(code):
    data = urlencode({
        "client_id":     DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI
    }).encode()
    req = urllib.request.Request(
        "https://discord.com/api/oauth2/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Discord {e.code}: {body[:200]}")

def discord_get_user(access_token):
    req = urllib.request.Request(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        code   = qs.get("code",  [""])[0]
        error  = qs.get("error", [""])[0]

        if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
            self._redirect(APP_URL + "#discord-not-configured")
            return

        if error:
            err_desc = qs.get("error_description", [""])[0]
            self._redirect(f"{APP_URL}#discord-error&msg={error}:{err_desc[:60]}")
            return

        # Pas de code = lancer OAuth2 — redirige vers la page app avec le code
        if not code:
            params = urlencode({
                "client_id":     DISCORD_CLIENT_ID,
                "redirect_uri":  REDIRECT_URI,
                "response_type": "code",
                "scope":         "identify",
                "prompt":        "consent"
            })
            self._redirect("https://discord.com/oauth2/authorize?" + params)
            return

        # Callback avec code — essai serveur, sinon renvoie à l'app pour échange client
        try:
            tokens       = discord_exchange_code(code)
            access_token = tokens["access_token"]
            user         = discord_get_user(access_token)

            discord_id     = user["id"]
            discord_name   = user.get("global_name") or user.get("username", "Membre")
            discord_avatar = user.get("avatar", "")
            if discord_avatar:
                discord_avatar = f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"

            token = make_token({
                "discord_id":   discord_id,
                "discord_name": discord_name,
                "avatar":       discord_avatar,
                "ts":           int(time.time())
            })

            self._redirect(f"{APP_URL}#token={token}")

        except Exception as e:
            # Échange serveur échoué — renvoie le code à l'app pour échange côté client
            self._redirect(f"{APP_URL}#discord-code={code}")

    def do_POST(self):
        """Proxy pour échange de token côté client (évite CORS Discord)"""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}

        code = body.get("code", "")
        if not code:
            self._respond({"error": "no code"}, 400)
            return

        try:
            tokens       = discord_exchange_code(code)
            access_token = tokens["access_token"]
            user         = discord_get_user(access_token)

            discord_id     = user["id"]
            discord_name   = user.get("global_name") or user.get("username", "Membre")
            discord_avatar = user.get("avatar", "")
            if discord_avatar:
                discord_avatar = f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"

            token = make_token({
                "discord_id":   discord_id,
                "discord_name": discord_name,
                "avatar":       discord_avatar,
                "ts":           int(time.time())
            })

            self._respond({"token": token, "discord_id": discord_id, "discord_name": discord_name, "avatar": discord_avatar})
        except Exception as e:
            self._respond({"error": str(e)[:200]}, 500)

    def _respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *a): pass
