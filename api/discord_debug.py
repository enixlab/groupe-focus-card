"""Debug endpoint pour Discord OAuth2"""
from http.server import BaseHTTPRequestHandler
import json, os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "1481723128588669040")
        DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "QqP4hS1etJcrVI-mvsBIvQ6qBJMRn0sa")
        APP_URL               = os.environ.get("APP_URL", "https://groupe-focus-card.vercel.app")

        body = json.dumps({
            "path": self.path,
            "client_id": DISCORD_CLIENT_ID,
            "secret_len": len(DISCORD_CLIENT_SECRET),
            "secret_prefix": DISCORD_CLIENT_SECRET[:6] + "...",
            "redirect_uri": APP_URL + "/api/discord",
            "app_url": APP_URL
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass
