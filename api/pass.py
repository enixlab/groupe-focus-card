"""
Vercel Python serverless — génère un .pkpass SIGNÉ PAR APPLE
via l'API publique WalletWallet (certificat Apple réel, 0 compte requis)
GET /api/pass?name=KARIM&pts=7&cycle=1&level=ACTIF
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, urllib.request, urllib.error

WALLETWALLET_API = "https://wallet-pass-api.workers2000.workers.dev/api/pkpass"
APP_URL = "https://groupe-focus-card.vercel.app"

# Strip doré pré-généré (375x123 PNG, gradient #C9A227→#F0D060)
# Chargé une seule fois au démarrage — zéro calcul au runtime
import os as _os
_strip_path = _os.path.join(_os.path.dirname(__file__), "_gold_strip.txt")
try:
    GOLD_STRIP_B64 = open(_strip_path).read().strip()
except Exception:
    GOLD_STRIP_B64 = ""


def generate_pass(name, pts, cycle, level, serial):
    pts_int   = int(pts) if str(pts).isdigit() else 0
    cycle_pts = pts_int % 10
    progress  = f"{cycle_pts}/10"
    member_url = APP_URL

    payload_dict = {
        "barcodeValue": member_url,
        "barcodeFormat": "PDF417",
        "colorPreset": "orange",
        "title": "MENTALITE FOCUS",
        "label": name[:20],
        "value": f"{progress} pts  •  Cycle #{cycle}  •  {level}",
        "backFields": [
            {
                "key": "card_link",
                "label": "Ma Carte Focus en ligne",
                "value": APP_URL,
                "attributedValue": f"<a href=\"{APP_URL}\">Ouvrir ma carte Focus</a>"
            },
            {
                "key": "discord_link",
                "label": "Rejoindre le Discord Focus",
                "value": "https://discord.gg/focus",
                "attributedValue": "<a href=\"https://discord.gg/focus\">Acceder au serveur Discord</a>"
            },
            {
                "key": "join_link",
                "label": "Devenir membre Focus",
                "value": "https://mentalitefocus.com/",
                "attributedValue": "<a href=\"https://mentalitefocus.com/\">S'abonner a 9.90/mois</a>"
            },
            {
                "key": "notif_info",
                "label": "Notifications Live",
                "value": "Ouvre ta carte en ligne et active les notifications pour etre alerte a chaque live."
            },
            {
                "key": "member_info",
                "label": "Infos membre",
                "value": f"Nom: {name} | Niveau: {level} | Cycle: #{cycle} | Points: {pts_int}"
            }
        ],
    }

    if GOLD_STRIP_B64:
        payload_dict["stripImage"] = GOLD_STRIP_B64

    payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        WALLETWALLET_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs     = parse_qs(urlparse(self.path).query)
        name   = qs.get("name",   ["MEMBRE"])[0].upper()[:20]
        pts    = qs.get("pts",    ["0"])[0]
        cycle  = qs.get("cycle",  ["1"])[0]
        level  = qs.get("level",  ["MEMBRE"])[0].upper()
        serial = qs.get("serial", [f"MF{name[:6]}"])[0]

        try:
            pkpass = generate_pass(name, pts, cycle, level, serial)
            self.send_response(200)
            self.send_header("Content-Type",   "application/vnd.apple.pkpass")
            self.send_header("Content-Length", str(len(pkpass)))
            self.send_header("Cache-Control",  "no-cache, no-store")
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
