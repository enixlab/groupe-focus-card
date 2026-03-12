"""
Base de données — GitHub Repo ENIX-WAR-ROOM
Fichiers : subscriptions.json, members.json, offers.json, contests.json
"""
import json, urllib.request, urllib.error, base64, os, time

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO         = "enixlab/ENIX-WAR-ROOM"
HEADERS      = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Content-Type":  "application/json",
    "User-Agent":    "focus-card"
}

def _get_file(filename):
    """Lit un fichier JSON du repo. Retourne (data, sha)."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/focus/{filename}",
        headers=HEADERS
    )
    try:
        with urllib.request.urlopen(req) as r:
            d    = json.loads(r.read())
            data = json.loads(base64.b64decode(d["content"]).decode())
            return data, d["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise

def _put_file(filename, data, sha=None, message=None):
    """Écrit un fichier JSON dans le repo."""
    content = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    payload = {
        "message": message or f"Update {filename}",
        "content": content
    }
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/focus/{filename}",
        data=json.dumps(payload).encode(),
        headers=HEADERS,
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Exception(f"GitHub write error {e.code}: {e.read().decode()}")

def load(filename, default=None):
    """Charge un fichier, retourne default si absent."""
    data, sha = _get_file(filename)
    if data is None:
        return (default if default is not None else ([] if filename != "members.json" else {})), None
    return data, sha

def save(filename, data, sha=None):
    """Sauvegarde un fichier."""
    return _put_file(filename, data, sha)

def load_save(filename, default=None):
    """Shortcut : charge et retourne (data, sha)."""
    return load(filename, default)
