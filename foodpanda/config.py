import json
import os

CONFIG_DIR = os.path.expanduser("~/.foodpanda-cli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "token": "",
    "latitude": 0.0,
    "longitude": 0.0,
    "address": "",
    "postal_code": "",
}


def _read_chrome_token() -> str:
    """Read foodpanda token from Chrome. Tries CDP first (live), then cookie DB."""
    token = _read_token_cdp()
    if not token:
        token = _read_token_cookie_db()
    return token


def _get_chrome_cookies() -> list[dict]:
    """Read all foodpanda.sg cookies from Chrome's cookie DB."""
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".foodpanda.sg")
        cookies = []
        for c in cj:
            cookies.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": bool(c.secure),
                "httpOnly": bool(getattr(c, "has_nonstandard_attr", lambda x: False)("HttpOnly")),
            })
        return cookies
    except Exception:
        return []


def refresh_token() -> str:
    """Refresh token by injecting Chrome cookies into Playwright and visiting foodpanda.sg.

    1. Read all foodpanda.sg cookies from Chrome's cookie DB (browser_cookie3)
    2. Launch Playwright Chromium with those cookies
    3. Navigate to foodpanda.sg to trigger server-side token refresh
    4. Return the new token cookie value
    """
    cookies = _get_chrome_cookies()
    if not cookies:
        return ""

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # Inject Chrome cookies into Playwright context
            context.add_cookies(cookies)

            page = context.new_page()
            page.goto("https://www.foodpanda.sg/", wait_until="networkidle", timeout=20000)

            # Read refreshed cookies
            new_cookies = context.cookies(["https://www.foodpanda.sg"])
            browser.close()

            for c in new_cookies:
                if c["name"] == "token":
                    return _validate_token(c["value"])
    except Exception:
        pass
    return ""


def _read_token_cdp() -> str:
    """Read token from running Chrome via CDP (port 9222)."""
    try:
        import httpx, websocket
        resp = httpx.get("http://127.0.0.1:9222/json", timeout=2)
        tabs = resp.json()
        ws_url = tabs[0]["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url, timeout=3)
        ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": ["https://www.foodpanda.sg"]},
        }))
        result = json.loads(ws.recv())
        ws.close()
        for c in result.get("result", {}).get("cookies", []):
            if c["name"] == "token":
                return _validate_token(c["value"])
    except Exception:
        pass
    return ""


def _read_token_cookie_db() -> str:
    """Read token from Chrome cookie database file."""
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".foodpanda.sg")
        for c in cj:
            if c.name == "token":
                return _validate_token(c.value)
    except Exception:
        pass
    return ""


def _validate_token(token: str) -> str:
    """Return token only if not expired."""
    try:
        import base64, time
        parts = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("expires", 0) > time.time():
            return token
    except Exception:
        return token  # can't parse, return anyway
    return ""


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
            config = {**DEFAULT_CONFIG, **saved}
    else:
        config = dict(DEFAULT_CONFIG)
    # Auto-refresh token from Chrome cookies (only if valid)
    chrome_token = _read_chrome_token()
    if chrome_token:
        config["token"] = chrome_token
    return config


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
