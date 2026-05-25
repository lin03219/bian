# -*- coding: utf-8 -*-
"""Auto-update via GitHub Releases"""
import json, os, sys, tempfile, shutil
from pathlib import Path
import requests

GITHUB_REPO = "lin03219/bian"
CURRENT_VERSION = "1.4.0"
VERSION_FILE = Path(os.path.expanduser("~")) / ".crypto_monitor" / "version.txt"

def get_current_version():
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return CURRENT_VERSION

def save_version(v):
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(v)

def _get_proxy():
    try:
        from config import get_config
        url = get_config().get('proxy', '')
        return {'http': url, 'https': url} if url else None
    except:
        return None

def check_update():
    """Returns (has_update, latest_version, download_url, body) or None on error"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        resp = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github.v3+json"}, proxies=_get_proxy())
        if resp.status_code != 200:
            print(f'[UPDATER] API returned {resp.status_code}')
            return None
        data = resp.json()
        latest = data["tag_name"].lstrip("v")
        current = get_current_version()
        if latest != current:
            # Find the .exe asset
            for asset in data.get("assets", []):
                if asset["name"].endswith(".exe"):
                    return True, latest, asset["browser_download_url"], data.get("body", "")
        return False, latest, "", ""
    except Exception:
        return None

def download_and_replace(download_url, callback=None):
    """Download new exe to temp, then replace current exe."""
    try:
        exe_path = sys.executable
        tmp = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
        tmp_path = tmp.name
        tmp.close()
        
        resp = requests.get(download_url, stream=True, timeout=120, proxies=_get_proxy())
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if callback and total > 0:
                    callback(downloaded, total)
        
        # Replace: rename old, move new
        old_path = exe_path + ".old"
        if os.path.exists(old_path):
            os.remove(old_path)
        os.rename(exe_path, old_path)
        shutil.move(tmp_path, exe_path)
        return True, ""
    except Exception as e:
        return False, str(e)
