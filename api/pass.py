"""
Vercel Python serverless — génère un .pkpass SIGNÉ PAR APPLE
via l'API publique WalletWallet (certificat Apple réel, 0 compte requis)
GET /api/pass?name=KARIM&pts=7&cycle=1&level=ACTIF
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import json, urllib.request, urllib.error
import zlib, struct, base64

WALLETWALLET_API = "https://wallet-pass-api.workers2000.workers.dev/api/pkpass"
APP_URL = "https://groupe-focus-card.vercel.app"

# ─── PIXEL FONT (lettres 5x7) ──────────────────────────────────────────────
FONT5 = {
    'M':[[1,0,0,0,1],[1,1,0,1,1],[1,0,1,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1]],
    'E':[[1,1,1,1,1],[1,0,0,0,0],[1,1,1,1,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,1,1,1,1]],
    'N':[[1,0,0,0,1],[1,1,0,0,1],[1,0,1,0,1],[1,0,0,1,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1]],
    'T':[[1,1,1,1,1],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0]],
    'A':[[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,1,1,1,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1]],
    'L':[[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,1,1,1,1]],
    'I':[[1,1,1,1,1],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[1,1,1,1,1]],
    'É':[[1,1,1,1,1],[1,0,0,0,0],[1,1,1,1,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,1,1,1,1]],
    ' ':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
    'F':[[1,1,1,1,1],[1,0,0,0,0],[1,1,1,1,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0]],
    'O':[[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[0,1,1,1,0]],
    'C':[[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,1],[0,1,1,1,0]],
    'U':[[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[0,1,1,1,0]],
    'S':[[0,1,1,1,1],[1,0,0,0,0],[1,0,0,0,0],[0,1,1,1,0],[0,0,0,0,1],[0,0,0,0,1],[1,1,1,1,0]],
    'G':[[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,0],[1,0,1,1,1],[1,0,0,0,1],[1,0,0,0,1],[0,1,1,1,0]],
    'R':[[1,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,1,1,1,0],[1,0,1,0,0],[1,0,0,1,0],[1,0,0,0,1]],
    'P':[[1,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,1,1,1,0],[1,0,0,0,0],[1,0,0,0,0],[1,0,0,0,0]],
    '·':[[0],[0],[0],[1],[0],[0],[0]],
    '#':[[0,1,0,1,0],[0,1,0,1,0],[1,1,1,1,1],[0,1,0,1,0],[1,1,1,1,1],[0,1,0,1,0],[0,1,0,1,0]],
}

def render_text(text, img, x_start, y_start, color, scale=2):
    """Render pixel font text onto image array"""
    x = x_start
    for ch in text.upper():
        glyph = FONT5.get(ch, FONT5[' '])
        gw = len(glyph[0])
        for row_i, row in enumerate(glyph):
            for col_i, px in enumerate(row):
                if px:
                    for sy in range(scale):
                        for sx in range(scale):
                            py = y_start + row_i * scale + sy
                            px_ = x + col_i * scale + sx
                            if 0 <= py < len(img) and 0 <= px_ < len(img[0]):
                                img[py][px_] = color
        x += (gw + 1) * scale
    return x

def create_strip_png(width=375, height=123, name="FOCUS", pts_int=0, cycle="1"):
    """Gold gradient strip with MENTALITE FOCUS branding and stats"""
    # Create pixel grid (RGB)
    img = [[[0, 0, 0] for _ in range(width)] for _ in range(height)]

    # Gold gradient background
    for y in range(height):
        t = y / (height - 1)
        for x in range(width):
            tx = x / (width - 1)
            # Dark gold gradient
            r = max(0, min(255, int(40 + tx * 180)))
            g = max(0, min(255, int(20 + tx * 120)))
            b_ = max(0, min(255, int(0 + tx * 15)))
            # Add vertical gradient overlay
            r = int(r * (1 - t * 0.3))
            g = int(g * (1 - t * 0.3))
            img[y][x] = [r, g, b_]

    # Thin bright gold line at top
    for x in range(width):
        img[0][x] = [255, 215, 0]
        img[1][x] = [220, 180, 40]

    # White text: "MENTALITE FOCUS"
    gold_text = [255, 255, 255]
    render_text("MENTALITE FOCUS", img, 16, 12, gold_text, scale=2)

    # Subtitle: membership card
    gold_dim = [200, 160, 60]
    render_text("CARTE DE FIDELITE", img, 16, 38, gold_dim, scale=1)

    # Stats line: points + cycle
    pts_str = f"{pts_int} PTS"
    render_text(pts_str, img, 16, 52, gold_text, scale=2)
    render_text(f"CYCLE #{cycle}", img, 16 + (len(pts_str) + 3) * 6 + 10, 52, gold_dim, scale=2)

    # Member name on right
    name_short = name[:10]
    name_x = width - len(name_short) * 12 - 16
    render_text(name_short, img, max(16, name_x), 78, [255, 240, 180], scale=2)

    # Convert to bytes
    raw_rows = []
    for row in img:
        raw_rows.append(b"\x00" + b"".join(bytes(px) for px in row))
    raw = b"".join(raw_rows)
    compressed = zlib.compress(raw, 9)

    def chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def generate_pass(name, pts, cycle, level, serial):
    pts_int   = int(pts) if str(pts).isdigit() else 0
    cycle_pts = pts_int % 10
    progress  = f"{cycle_pts}/10"

    # Barcode = URL directe vers l'app Focus
    member_url = APP_URL

    # Generate branded strip image
    strip_png = create_strip_png(375, 123, name=name, pts_int=pts_int, cycle=cycle)
    strip_b64 = base64.b64encode(strip_png).decode()

    payload = json.dumps({
        "barcodeValue": member_url,
        "barcodeFormat": "PDF417",
        "colorPreset": "dark",
        "title": "MENTALITE FOCUS",
        "label": name[:20],
        "value": f"{progress} pts  •  Cycle #{cycle}  •  {level}",
        "stripImage": strip_b64,
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
    }, ensure_ascii=False).encode("utf-8")

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
