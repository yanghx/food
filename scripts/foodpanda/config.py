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

# --- Chrome cookie cache (avoid decrypting cookie DB multiple times per process) ---

_chrome_cookies_cache: list[dict] | None = None


def _get_chrome_cookies() -> list[dict]:
    """Read all foodpanda.sg cookies from Chrome's cookie DB (no Chrome process needed).
    Cached per process to avoid repeated decryption."""
    global _chrome_cookies_cache
    if _chrome_cookies_cache is not None:
        return _chrome_cookies_cache
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
        _chrome_cookies_cache = cookies
        return cookies
    except Exception:
        _chrome_cookies_cache = []
        return []


def _get_chrome_cookie_value(name: str) -> str:
    """Read a single cookie value from cached Chrome cookies."""
    for c in _get_chrome_cookies():
        if c["name"] == name:
            return c["value"]
    return ""


def _read_chrome_token() -> str:
    """Read valid (non-expired) foodpanda token from Chrome. Tries CDP first, then cookie DB."""
    token = _read_token_cdp()
    if not token:
        token = _validate_token(_get_chrome_cookie_value("token"))
    return token


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


# --- Token refresh strategies ---

def _refresh_via_api(refresh_tok: str, device_tok: str = "") -> dict:
    """Refresh token via API call — no browser needed.

    Uses POST /api/v5/auth/customers with the refresh_token.
    Returns {"token": ..., "refresh_token": ..., "device_token": ...} on success,
    or {"error": "..."} on failure.
    """
    import httpx
    import uuid

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "x-fp-api-key": "volo",
        "x-pd-language-id": "1",
        "x-country-code": "sg",
        "Origin": "https://www.foodpanda.sg",
        "Referer": "https://www.foodpanda.sg/",
        "perseus-client-id": str(uuid.uuid4()),
        "perseus-session-id": str(uuid.uuid4()),
    }
    if device_tok:
        headers["Authorization"] = f"Bearer {device_tok}"

    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://sg.fd-api.com/api/v5/auth/customers",
                json=body,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                inner = data.get("data", data)
                token = inner.get("token", "")
                new_refresh = inner.get("refresh_token", "")
                new_device = inner.get("device_token", "")
                if token and _validate_token(token):
                    return {
                        "token": token,
                        "refresh_token": new_refresh or refresh_tok,
                        "device_token": new_device or device_tok,
                    }
            if resp.status_code == 429:
                retry = resp.headers.get("retry-after", "")
                try:
                    mins = f" ({int(retry) // 60}m)" if retry else ""
                except ValueError:
                    mins = ""
                return {"error": f"rate_limited{mins}"}
            return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def _refresh_via_playwright(cookies: list[dict] | None = None) -> str:
    """Refresh token by launching headless Chromium with Chrome cookies (legacy fallback)."""
    if cookies is None:
        cookies = _get_chrome_cookies()
    if not cookies:
        return ""

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()
            page.goto("https://www.foodpanda.sg/", wait_until="networkidle", timeout=20000)
            new_cookies = context.cookies(["https://www.foodpanda.sg"])
            browser.close()

            for c in new_cookies:
                if c["name"] == "token":
                    return _validate_token(c["value"])
    except Exception:
        pass
    return ""


def _extract_chrome_credentials() -> dict:
    """Extract refresh_token and device_token from cached Chrome cookies.

    Returns {"refresh_token": "...", "device_token": "..."} or {}.
    """
    rt = _get_chrome_cookie_value("refresh_token")
    dt = _get_chrome_cookie_value("device_token")
    if rt:
        return {"refresh_token": rt, "device_token": dt}
    return {}


def _sync_chrome_credentials_to_config(config: dict) -> dict:
    """If Chrome has newer credentials, merge them into config dict (and persist)."""
    creds = _extract_chrome_credentials()
    if not creds.get("refresh_token"):
        return config
    updated = False
    for key in ("refresh_token", "device_token"):
        if creds.get(key) and config.get(key) != creds[key]:
            config[key] = creds[key]
            updated = True
    if updated:
        save_config(config)
    return config


# --- Public API ---

def refresh_token() -> str:
    """Refresh token. Tries API first (no browser), then Playwright as fallback.

    Strategy:
    1. Use saved refresh_token from config → API call (fastest, no deps)
    2. Read refresh_token from Chrome cookie DB → API call (no Chrome process needed)
    3. Playwright headless Chromium with Chrome cookies (legacy fallback)

    Returns new token string, or "" on failure.
    Sets refresh_token.last_error for diagnostics.
    """
    refresh_token.last_error = ""
    config = _load_raw_config()
    api_tried = False

    # Strategy 1: API refresh with saved credentials
    rt = config.get("refresh_token", "")
    dt = config.get("device_token", "")
    if rt:
        result = _refresh_via_api(rt, dt)
        api_tried = True
        if result.get("token"):
            config["token"] = result["token"]
            config["refresh_token"] = result.get("refresh_token", rt)
            config["device_token"] = result.get("device_token", dt)
            save_config(config)
            return result["token"]
        if result.get("error"):
            refresh_token.last_error = result["error"]

    # Strategy 2: Read fresh credentials from Chrome cookie DB, then API refresh
    # Skip if strategy 1 already hit rate limit
    if not api_tried or "rate_limited" not in refresh_token.last_error:
        creds = _extract_chrome_credentials()
        new_rt = creds.get("refresh_token", "")
        new_dt = creds.get("device_token", "")
        if new_rt and new_rt != rt:
            result = _refresh_via_api(new_rt, new_dt)
            if result.get("token"):
                config["token"] = result["token"]
                config["refresh_token"] = result.get("refresh_token", new_rt)
                config["device_token"] = result.get("device_token", new_dt)
                save_config(config)
                return result["token"]
            if result.get("error"):
                refresh_token.last_error = result["error"]

    # Strategy 3: Playwright fallback (needs playwright + chromium installed)
    token = _refresh_via_playwright()
    if token:
        refresh_token.last_error = ""
        return token

    return ""

refresh_token.last_error = ""


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

    # Token expired or missing — try lightweight refresh (no Playwright)

    # 1. Try reading a fresh valid token from Chrome cookie DB (fast, no network)
    chrome_token = _read_chrome_token()
    if chrome_token:
        config["token"] = chrome_token
        config = _sync_chrome_credentials_to_config(config)
        return config

    # 2. Try API refresh with refresh_token (one HTTP call, no browser)
    rt = config.get("refresh_token", "")
    dt = config.get("device_token", "")
    if not rt:
        config = _sync_chrome_credentials_to_config(config)
        rt = config.get("refresh_token", "")
        dt = config.get("device_token", "")
    if rt:
        result = _refresh_via_api(rt, dt)
        if result.get("token"):
            config["token"] = result["token"]
            config["refresh_token"] = result.get("refresh_token", rt)
            config["device_token"] = result.get("device_token", dt)
            save_config(config)

    return config


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)
