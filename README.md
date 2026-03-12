# fd — Foodpanda Singapore CLI

A command-line tool for ordering food on [Foodpanda Singapore](https://www.foodpanda.sg). Designed for both human and AI agent usage.

## Install

```bash
# Clone & install
git clone <repo-url> && cd food
pip install -e .

# Install Playwright browser (for token refresh)
playwright install chromium
```

Dependencies: `rich`, `httpx`, `click`, `playwright`, `browser-cookie3`

## Quick Start

```bash
# 1. Set your token (from browser cookies — see "Authentication" below)
fd token eyJhbG...

# 2. Set delivery address
fd address 123456        # by postal code
fd address               # or pick from saved addresses

# 3. Search & order
fd search 'chicken rice'
fd menu g9xw             # view menu by restaurant code
fd add g9xw:3 -n 2       # add item #3, qty 2
fd cart                   # review cart
fd checkout               # place order (pandapay)
```

## Commands

| Command | Description |
|---|---|
| `fd address [postal]` | Set delivery address. No args = pick from saved addresses |
| `fd token [value]` | Set or view login token |
| `fd refresh` | Auto-refresh token from Chrome cookies via Playwright |
| `fd search <name>` | Search restaurants by name |
| `fd search-food <name>` | Search for specific dishes across restaurants |
| `fd menu <code>` | View a restaurant's full menu |
| `fd add <code>:<#> [-n qty]` | Add menu item to cart (e.g. `fd add g9xw:3 -n 2`) |
| `fd cart` | View current cart |
| `fd clear` | Clear cart |
| `fd checkout` | Place order |
| `fd orders` | View order history |
| `fd reorder [#]` | Re-order from history |

### Checkout Options

```bash
fd checkout                          # immediate, pandapay
fd checkout --dry-run                # calculate price only
fd checkout --time 13:00             # scheduled delivery
fd checkout --time 'tomorrow 18:30'  # tomorrow
fd checkout --voucher SAVE5          # apply voucher
fd checkout --note 'leave at door'   # delivery note
fd checkout --json                   # JSON output (for AI)
```

## Authentication

`fd` needs a Foodpanda bearer token to place orders and view history. Public endpoints (search, menu) work without a token.

**Option A — Manual:** Copy the `token` cookie from your browser's DevTools on foodpanda.sg:

```bash
fd token eyJhbGciOiJSUz...
```

**Option B — Auto-refresh:** If you're logged into Foodpanda in Chrome, `fd` can read and refresh your token automatically:

```bash
fd refresh
```

This uses `browser-cookie3` to read Chrome cookies and `Playwright` to perform a headless visit that refreshes the token. On every `fd` command, the token is also auto-read from Chrome if available.

## JSON Mode

Most commands support `--json` for machine-readable output, making `fd` easy to integrate with AI agents:

```bash
fd search 'sushi' --json
fd menu g9xw --json
fd cart --json
fd checkout --json --dry-run
```

## How It Works

1. **Address resolution** — Singapore postal codes are resolved via the [OneMap API](https://www.onemap.gov.sg)
2. **Restaurant search** — Uses the Delivery Hero Disco listing API
3. **Menu & vendor details** — Fetched from `sg.fd-api.com` (public, no auth)
4. **Checkout flow** — `cart/calculate` → `purchase/intent` → `cart/checkout` (requires auth)
5. **Cart persistence** — Stored locally at `~/.foodpanda-cli/cart.json`
6. **Config** — Stored at `~/.foodpanda-cli/config.json`

## Project Structure

```
foodpanda/
  cli.py         # Click commands & UI (Rich tables)
  api.py         # FoodpandaAPI — all HTTP calls
  models.py      # Restaurant, MenuItem, Cart dataclasses
  cart_store.py   # Persistent cart (JSON file)
  config.py      # Config management & token refresh
setup.py         # Package setup, entry point: fd
```

## Requirements

- Python 3.12+
- Chrome (for auto token refresh)
- A Foodpanda Singapore account
