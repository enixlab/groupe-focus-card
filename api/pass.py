"""
Apple Wallet .pkpass — signé avec certificat Apple Developer (Python pur)
GET /api/pass?name=KARIM&pts=7&cycle=1&level=ACTIF
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import json, os, hashlib, zipfile, io

APP_URL = "https://groupe-focus-card.vercel.app"
PASS_TYPE_ID = "pass.com.mentalitefocus.loyalty"
TEAM_ID = "TRX9J5U7L6"

CERTS_DIR = os.path.join(os.path.dirname(__file__), "certs")

# Charger certificats et clé au démarrage
def _load_file(name):
    p = os.path.join(CERTS_DIR, name)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    return b""

_cert_pem = _load_file("certificate.pem")
_key_pem = _load_file("pass_private.key")
_wwdr_pem = _load_file("wwdr.pem")

# Charger les assets PNG
_assets = {}
for _fname in ["icon.png", "icon@2x.png", "logo.png", "logo@2x.png", "strip.png", "strip@2x.png"]:
    data = _load_file(_fname)
    if data:
        _assets[_fname] = data


def _sign_manifest(manifest_bytes):
    """Signe le manifest.json avec PKCS#7 DER en Python pur (cryptography + asn1)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509 import load_pem_x509_certificate

    cert = load_pem_x509_certificate(_cert_pem)
    key = serialization.load_pem_private_key(_key_pem, password=None)
    wwdr = load_pem_x509_certificate(_wwdr_pem)

    # PKCS7 sign (DER)
    signature = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(manifest_bytes)
        .add_signer(cert, key, hashes.SHA256())
        .add_certificate(wwdr)
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    return signature


def build_pass_json(name, pts_int, cycle, level):
    cycle_pts = pts_int % 10
    progress = f"{cycle_pts}/10"
    member_url = f"{APP_URL}?wallet_name={quote(name)}&wallet_pts={pts_int}&wallet_cycle={cycle}&wallet_level={quote(level)}"

    prog_bar = "".join(["●" if i < cycle_pts else "○" for i in range(10)])
    next_reward = 10 - cycle_pts

    return {
        "formatVersion": 1,
        "passTypeIdentifier": PASS_TYPE_ID,
        "serialNumber": f"FOCUS-{name[:10]}-{pts_int}-{cycle}",
        "teamIdentifier": TEAM_ID,
        "organizationName": "Mentalite Focus",
        "description": "Carte de fidelite Mentalite Focus",
        "logoText": "MENTALITE FOCUS",

        "backgroundColor": "rgb(42, 32, 0)",
        "foregroundColor": "rgb(240, 208, 96)",
        "labelColor": "rgb(180, 150, 60)",

        "storeCard": {
            "headerFields": [
                {
                    "key": "pts_header",
                    "label": "POINTS",
                    "value": str(pts_int),
                    "textAlignment": "PKTextAlignmentRight"
                }
            ],
            "primaryFields": [
                {
                    "key": "name",
                    "label": "CARTE DE",
                    "value": name
                }
            ],
            "secondaryFields": [
                {
                    "key": "website",
                    "label": "MA CARTE",
                    "value": "groupe-focus-card.vercel.app"
                }
            ],
            "auxiliaryFields": [
                {
                    "key": "level_aux",
                    "label": "NIVEAU",
                    "value": level
                },
                {
                    "key": "cycle_aux",
                    "label": "CYCLE",
                    "value": f"#{cycle}"
                },
                {
                    "key": "prog_aux",
                    "label": "PROGRESSION",
                    "value": progress
                }
            ],
            "backFields": [
                {
                    "key": "stats",
                    "label": "━━━  MES STATISTIQUES  ━━━",
                    "value": f"Points : {pts_int}\nCycle : #{cycle}\nProgression : {progress}\nProchain reward : {next_reward} lives\n\n{prog_bar}"
                },
                {
                    "key": "card_link",
                    "label": "━━━  MA CARTE EN LIGNE  ━━━",
                    "value": member_url,
                    "attributedValue": f"<a href='{member_url}'>Ouvrir ma carte Focus</a>"
                },
                {
                    "key": "discord",
                    "label": "━━━  DISCORD  ━━━",
                    "value": "https://discord.gg/AerNKK5zYF",
                    "attributedValue": "<a href='https://discord.gg/AerNKK5zYF'>Rejoindre Focus (+2000 membres)</a>"
                },
                {
                    "key": "join",
                    "label": "━━━  ABONNEMENT  ━━━",
                    "value": "9.90/mois",
                    "attributedValue": "<a href='https://mentalitefocus.com/'>Rejoindre Mentalite Focus</a>"
                },
                {
                    "key": "howto",
                    "label": "━━━  COMMENT CA MARCHE  ━━━",
                    "value": "1 live = 1 point\n10 points = 1 cycle = 1 reward\n\nNiveaux : MEMBRE → ACTIF → AVANCE → EXPERT → ELITE"
                }
            ]
        },

        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": member_url,
                "messageEncoding": "iso-8859-1",
                "altText": "groupe-focus-card.vercel.app"
            }
        ],
    }


def create_pkpass(name, pts, cycle, level):
    pts_int = int(pts) if str(pts).isdigit() else 0
    pass_json = build_pass_json(name, pts_int, cycle, level)
    pass_bytes = json.dumps(pass_json, ensure_ascii=False).encode("utf-8")

    # Manifest: SHA1 de chaque fichier
    manifest = {"pass.json": hashlib.sha1(pass_bytes).hexdigest()}
    for fname, data in _assets.items():
        manifest[fname] = hashlib.sha1(data).hexdigest()
    manifest_bytes = json.dumps(manifest).encode("utf-8")

    # Signature PKCS#7
    signature = _sign_manifest(manifest_bytes)

    # ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pass.json", pass_bytes)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("signature", signature)
        for fname, data in _assets.items():
            zf.writestr(fname, data)
    return buf.getvalue()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        name = qs.get("name", ["MEMBRE"])[0].upper()[:20]
        pts = qs.get("pts", ["0"])[0]
        cycle = qs.get("cycle", ["1"])[0]
        level = qs.get("level", ["MEMBRE"])[0].upper()

        try:
            pkpass = create_pkpass(name, pts, cycle, level)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.pkpass")
            self.send_header("Content-Length", str(len(pkpass)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(pkpass)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def log_message(self, *a): pass
