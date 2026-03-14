import json
import os
import sys

CONFIG_DIR = os.path.expanduser("~/.foodpanda-cli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "token": "",
    "latitude": 0.0,
    "longitude": 0.0,
    "address": "",
    "postal_code": "",
}

# --- Chrome cookie reading ---


def _read_chrome_cookies() -> dict[str, str]:
    """Read foodpanda.sg cookies from Chrome's cookie DB. Returns {name: value}.

    Always reads fresh from disk (no caching) to pick up browser-side refreshes.
    """
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".foodpanda.sg")
        return {c.name: c.value for c in cj}
    except Exception:
        return {}


def _get_chrome_cookies() -> list[dict]:
    """Read all foodpanda.sg cookies as list-of-dicts (for Playwright compatibility)."""
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".foodpanda.sg")
        return [{
            "name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "secure": bool(c.secure),
            "httpOnly": bool(getattr(c, "has_nonstandard_attr", lambda x: False)("HttpOnly")),
        } for c in cj]
    except Exception:
        return []


# --- Token validation ---

def _validate_token(token: str) -> str:
    """Return token only if it's a valid, non-expired JWT. Returns "" otherwise."""
    if not token:
        return ""
    try:
        import base64, time
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("expires", 0) > time.time():
            return token
    except Exception:
        return ""
    return ""


# --- Chrome-based token refresh ---

def _refresh_via_chrome() -> str:
    """Refresh token by telling Chrome to visit foodpanda.sg (triggers site's own JS refresh).

    Uses AppleScript on macOS to navigate Chrome to foodpanda.sg, waits for the
    page to load and refresh the token, then re-reads cookies from Chrome's DB.

    Returns new valid token string, or "" on failure.
    """
    if sys.platform != "darwin":
        return ""

    import subprocess, time

    applescript = '''
tell application "Google Chrome"
    set found to false
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "foodpanda.sg" then
                set URL of t to "https://www.foodpanda.sg/"
                set found to true
                exit repeat
            end if
        end repeat
        if found then exit repeat
    end repeat
    if not found then
        tell front window
            make new tab with properties {URL:"https://www.foodpanda.sg/"}
        end tell
    end if
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return ""
    except Exception:
        return ""

    # Wait for Chrome to load the page and refresh cookies
    for wait in (6, 4, 4):
        time.sleep(wait)
        cookies = _read_chrome_cookies()
        token = _validate_token(cookies.get("token", ""))
        if token:
            return token

    return ""


# --- Public API ---

def refresh_token() -> str:
    """Refresh the foodpanda auth token.

    Strategy:
    1. Read token from Chrome cookie DB (instant — picks up browser-side refreshes)
    2. Tell Chrome to visit foodpanda.sg (triggers the site's JS token refresh),
       then re-read cookies

    Returns new token string, or "" on failure.
    Sets refresh_token.last_error for diagnostics.
    """
    refresh_token.last_error = ""
    config = _load_raw_config()

    # Strategy 1: Chrome cookie DB may already have a fresh token
    cookies = _read_chrome_cookies()
    token = _validate_token(cookies.get("token", ""))
    if token:
        config["token"] = token
        _sync_chrome_credentials(config, cookies)
        save_config(config)
        return token

    # Strategy 2: Open foodpanda.sg in Chrome to trigger token refresh
    token = _refresh_via_chrome()
    if token:
        config["token"] = token
        # Re-read cookies for refresh_token/device_token
        cookies = _read_chrome_cookies()
        _sync_chrome_credentials(config, cookies)
        save_config(config)
        return token

    refresh_token.last_error = "Chrome 未能刷新 token (确保已登录 foodpanda.sg)"
    return ""

refresh_token.last_error = ""


def _sync_chrome_credentials(config: dict, cookies: dict[str, str]):
    """Merge refresh_token and device_token from Chrome cookies into config."""
    for key in ("refresh_token", "device_token"):
        val = cookies.get(key, "")
        if val:
            config[key] = val


def _load_raw_config() -> dict:
    """Load config from file without any auto-refresh logic."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
    return dict(DEFAULT_CONFIG)


def load_config() -> dict:
    config = _load_raw_config()

    # If saved token is still valid, use it
    if _validate_token(config.get("token", "")):
        return config

    # Token expired or missing — try reading fresh token from Chrome cookie DB
    cookies = _read_chrome_cookies()
    token = _validate_token(cookies.get("token", ""))
    if token:
        config["token"] = token
        _sync_chrome_credentials(config, cookies)
        save_config(config)

    return config


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)
