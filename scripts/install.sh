#!/usr/bin/env bash
# Install foodpanda CLI (fd) into a virtualenv
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv if not exists
if [ ! -d "$VENV_DIR" ]; then
    echo "[foodpanda] Creating virtualenv..."
    python3 -m venv "$VENV_DIR"
fi

# Install package
echo "[foodpanda] Installing dependencies..."
"$VENV_DIR/bin/pip" install -q -e "$SCRIPT_DIR"

# Install Playwright browser
if ! "$VENV_DIR/bin/python" -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "[foodpanda] Installing Playwright chromium..."
    "$VENV_DIR/bin/playwright" install chromium 2>/dev/null || true
fi

# Create wrapper script at ~/.local/bin/fd
WRAPPER_DIR="$HOME/.local/bin"
mkdir -p "$WRAPPER_DIR"
cat > "$WRAPPER_DIR/fd" << WRAPPER
#!/usr/bin/env bash
exec "$VENV_DIR/bin/fd" "\$@"
WRAPPER
chmod +x "$WRAPPER_DIR/fd"

echo "[foodpanda] Installed successfully!"
echo "[foodpanda] Command: fd (at $WRAPPER_DIR/fd)"
echo "[foodpanda] Make sure $WRAPPER_DIR is in your PATH"
