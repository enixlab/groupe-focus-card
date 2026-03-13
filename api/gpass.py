"""
Google Wallet Pass — Loyalty Card
GET /api/gpass?name=KARIM&pts=7&cycle=1&level=ACTIF

Génère un lien "Save to Google Wallet" avec un JWT signé.
Utilise le format Generic Pass (pas besoin de Google Pay Issuer pour le test).
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import json, os, time, hashlib, base64, hmac

APP_URL = "https://groupe-focus-card.vercel.app"
ISSUER_ID = os.environ.get("GOOGLE_WALLET_ISSUER_ID", "")
# Si pas de service account Google, on utilise le mode "JWT unsigned"
# qui redirige vers une page web de la carte

def _b64url(data):
    """Base64 URL-safe sans padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def build_wallet_url(name, pts_int, cycle, level):
    """
    Construit un lien Google Wallet "Add to Wallet".
    Sans Issuer ID Google, on redirige vers la PWA avec les params.
    Avec Issuer ID, on génère un vrai JWT Google Wallet.
    """
    cycle_pts = pts_int % 10
    progress = f"{cycle_pts}/10"
    prog_bar = "".join(["●" if i < cycle_pts else "○" for i in range(10)])

    if ISSUER_ID:
        # Mode Google Wallet API — JWT signé
        # Nécessite GOOGLE_SERVICE_ACCOUNT_KEY en env
        sa_key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
        if sa_key_json:
            return _build_google_jwt(name, pts_int, cycle, level, sa_key_json)

    # Mode fallback — Lien direct vers la PWA avec installation guidée
    member_url = f"{APP_URL}?wallet_name={quote(name)}&wallet_pts={pts_int}&wallet_cycle={cycle}&wallet_level={quote(level)}"

    # Générer un token unique pour ce pass
    token = hashlib.sha256(f"FOCUS-{name}-{pts_int}-{cycle}".encode()).hexdigest()[:16]

    # Créer le lien Google Wallet via le format "Save to Google Pay" link
    # Sans issuer, on utilise le lien PWA qui s'ajoute à l'écran d'accueil
    save_url = f"{APP_URL}?install=android&wallet_name={quote(name)}&wallet_pts={pts_int}&wallet_cycle={cycle}&wallet_level={quote(level)}&token={token}"

    return save_url


def _build_google_jwt(name, pts_int, cycle, level, sa_key_json):
    """Construit un JWT pour Google Wallet API (si service account configuré)."""
    import jwt  # PyJWT
    sa = json.loads(sa_key_json)

    now = int(time.time())
    serial = f"FOCUS-{name[:10]}-{pts_int}-{cycle}"

    payload = {
        "iss": sa["client_email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": now,
        "payload": {
            "genericObjects": [{
                "id": f"{ISSUER_ID}.{serial}",
                "classId": f"{ISSUER_ID}.FOCUS_LOYALTY",
                "header": {
                    "defaultValue": {"language": "fr", "value": f"FOCUS — {name}"}
                },
                "subheader": {
                    "defaultValue": {"language": "fr", "value": level}
                },
                "cardTitle": {
                    "defaultValue": {"language": "fr", "value": "Carte Focus"}
                },
                "hexBackgroundColor": "#D7AF32",
                "logo": {
                    "sourceUri": {"uri": f"{APP_URL}/icon-512.png"}
                },
                "heroImage": {
                    "sourceUri": {"uri": f"{APP_URL}/icon-512.png"}
                },
                "textModulesData": [
                    {"id": "points", "header": "POINTS", "body": str(pts_int)},
                    {"id": "cycle", "header": "CYCLE", "body": f"#{cycle}"},
                    {"id": "level", "header": "NIVEAU", "body": level},
                ],
                "barcode": {
                    "type": "QR_CODE",
                    "value": f"{APP_URL}?name={quote(name)}&pts={pts_int}",
                    "alternateText": serial
                },
                "state": "ACTIVE"
            }]
        },
        "origins": [APP_URL]
    }

    token = jwt.encode(payload, sa["private_key"], algorithm="RS256")
    return f"https://pay.google.com/gp/v/save/{token}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        name = qs.get("name", ["MEMBRE"])[0].upper()[:20]
        pts = qs.get("pts", ["0"])[0]
        cycle = qs.get("cycle", ["1"])[0]
        level = qs.get("level", ["MEMBRE"])[0].upper()

        try:
            pts_int = int(pts) if str(pts).isdigit() else 0
            save_url = build_wallet_url(name, pts_int, cycle, level)

            body = json.dumps({
                "ok": True,
                "save_url": save_url,
                "mode": "google_wallet" if ISSUER_ID else "pwa_install"
            }).encode()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err)

    def log_message(self, *a): pass
