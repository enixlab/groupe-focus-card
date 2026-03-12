"""
Discord OAuth2 — Connexion membre
GET /api/discord          → redirige vers Discord OAuth2
GET /api/discord?code=xxx → callback Discord → crée profil → redirige vers app
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import json, urllib.request, urllib.error, os, hashlib, hmac, time, base64

DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "1481723128588669040")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "QqP4hS1etJcrVI-mvsBIvQ6qBJMRn0sa")
DISCORD_GUILD_ID      = os.environ.get("DISCORD_GUILD_ID", "1481745584602742847")
GITHUB_TOKEN          = os.environ.get("GITHUB_TOKEN", "")
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

# ── GitHub Gist — membres ─────────────────────────────────────────────────────
def find_members_gist():
    req = urllib.request.Request(
        "https://api.github.com/gists?per_page=50",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "focus-card"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            for g in json.loads(r.read()):
                if "members.json" in g.get("files", {}):
                    return g["id"]
    except: pass
    # Créer le gist membres
    data = json.dumps({
        "description": "Mentalite Focus — Members",
        "public": False,
        "files": {"members.json": {"content": "{}"}}
    }).encode()
    req2 = urllib.request.Request(
        "https://api.github.com/gists", data=data,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json", "User-Agent": "focus-card"}
    )
    with urllib.request.urlopen(req2) as r:
        return json.loads(r.read())["id"]

def load_members(gid):
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gid}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "focus-card"}
    )
    with urllib.request.urlopen(req) as r:
        g = json.loads(r.read())
        return json.loads(g["files"]["members.json"]["content"])

def save_members(gid, members):
    data = json.dumps({"files": {"members.json": {"content": json.dumps(members)}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gid}", data=data,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json",
                 "User-Agent": "focus-card", "X-HTTP-Method-Override": "PATCH"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req): pass
    except: pass

def get_or_create_member(discord_id, discord_name, discord_avatar, guild_member=None):
    gid     = find_members_gist()
    members = load_members(gid)
    if discord_id in members:
        m = members[discord_id]
        m["discord_name"]   = discord_name
        m["discord_avatar"] = discord_avatar
        m["last_seen"]      = time.time()
        if guild_member:
            m["roles"] = guild_member.get("roles", [])
    else:
        m = {
            "discord_id":     discord_id,
            "discord_name":   discord_name,
            "discord_avatar": discord_avatar,
            "pts":            0,
            "cyclePoints":    0,
            "totalCycles":    0,
            "watchedLives":   [],
            "earned":         [],
            "tier":           "MEMBRE",
            "roles":          guild_member.get("roles", []) if guild_member else [],
            "joined_at":      time.time(),
            "last_seen":      time.time()
        }
    members[discord_id] = m
    save_members(gid, members)
    return m

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
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def discord_get_user(access_token):
    req = urllib.request.Request(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def discord_get_guild_member(access_token, guild_id):
    req = urllib.request.Request(
        f"https://discord.com/api/users/@me/guilds/{guild_id}/member",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except: return None

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        code   = qs.get("code",  [""])[0]
        error  = qs.get("error", [""])[0]

        # ── Pas encore configuré ──────────────────────────────────────────────
        if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
            self._redirect(APP_URL + "#discord-not-configured")
            return

        # ── Erreur OAuth2 ─────────────────────────────────────────────────────
        if error:
            self._redirect(APP_URL + "#discord-error")
            return

        # ── Pas de code = lancer OAuth2 ───────────────────────────────────────
        if not code:
            params = urlencode({
                "client_id":     DISCORD_CLIENT_ID,
                "redirect_uri":  REDIRECT_URI,
                "response_type": "code",
                "scope":         "identify guilds.members.read",
                "prompt":        "consent"
            })
            self._redirect("https://discord.com/oauth2/authorize?" + params)
            return

        # ── Callback avec code ────────────────────────────────────────────────
        try:
            tokens       = discord_exchange_code(code)
            access_token = tokens["access_token"]
            user         = discord_get_user(access_token)

            discord_id     = user["id"]
            discord_name   = user.get("global_name") or user.get("username", "Membre")
            discord_avatar = user.get("avatar", "")
            if discord_avatar:
                discord_avatar = f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"

            # Sauvegarder le profil (non bloquant)
            try:
                guild_member = None
                if DISCORD_GUILD_ID:
                    guild_member = discord_get_guild_member(access_token, DISCORD_GUILD_ID)
                get_or_create_member(discord_id, discord_name, discord_avatar, guild_member)
            except:
                pass  # Ne bloque pas la connexion

            # Générer token de session
            token = make_token({
                "discord_id":   discord_id,
                "discord_name": discord_name,
                "avatar":       discord_avatar,
                "ts":           int(time.time())
            })

            self._redirect(f"{APP_URL}#token={token}")

        except Exception as e:
            self._redirect(f"{APP_URL}#discord-error&msg={str(e)[:80]}")

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *a): pass
