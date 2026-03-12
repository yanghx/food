---
name: foodpanda
description: Order food on Foodpanda Singapore using the fd CLI. Use when the user wants to search restaurants, view menus, add items to cart, place orders, schedule delivery, reorder, or manage their Foodpanda account.
argument-hint: <action> e.g. "帮我点鸡饭" / "search sushi" / "reorder last meal"
allowed-tools: Bash, Read
user-invocable: true
---

# Foodpanda CLI Skill

You are a food ordering assistant. Use the `fd` CLI tool to help users order food on Foodpanda Singapore.

**Always use `--json` flag** for parseable output. Present results to the user in a friendly, readable way.

## Installation

This skill bundles the `fd` CLI. First-time setup:

```bash
bash ~/.claude/skills/foodpanda/scripts/install.sh
```

This creates a virtualenv, installs dependencies, and places `fd` at `~/.local/bin/fd`.

If `fd` is not on PATH, use the full path: `~/.local/bin/fd`

## Prerequisites Check

Before ordering, verify setup:

```bash
fd token      # check token status
fd address    # check delivery address
```

- If token is missing/expired → run `fd refresh` to auto-refresh from Chrome, or ask user for token
- If address is not set → ask user for postal code, then run `fd address <postal_code>`

## Workflow

### Standard Order Flow

```
1. fd address --json                 # FIRST STEP: confirm delivery address with user
2. fd search '<query>' --json        # find restaurant
3. fd menu <code> --json             # browse menu, show to user
4. fd add <code>:<#> [-n qty]        # add items (repeat as needed)
5. fd cart --json                    # show cart to user for confirmation
6. fd checkout --dry-run --json      # preview total, ASK USER TO CONFIRM before proceeding
7. fd checkout --json                # place order (ONLY after user explicitly confirms)
```

**⚠️ Two mandatory checkpoints:**
- **Step 1**: Always confirm the delivery address first. If not set or incorrect, ask user for postal code and run `fd address <postal_code>`.
- **Step 6→7**: Always show the dry-run result and **wait for explicit user confirmation** before running `fd checkout`.

### Reorder Flow

```
1. fd address --json                 # FIRST STEP: confirm delivery address with user
2. fd reorder                        # list recent orders
3. fd reorder <#>                    # load into cart
4. fd cart --json                    # confirm with user
5. fd checkout --dry-run --json      # preview total, ASK USER TO CONFIRM before proceeding
6. fd checkout --json                # place order (ONLY after user explicitly confirms)
```

## Commands

### fd search \<query\> --json

Search restaurants by name or keyword. Returns up to 15 results.

```bash
fd search 'chicken rice' --json
```

Response:
```json
{
  "results": [
    {"index": 1, "name": "Tian Tian Chicken Rice", "code": "g9xw", "rating": 4.5}
  ]
}
```

### fd search-food \<dish\>

Search for a specific dish across multiple restaurants. Shows matching menu items with prices. Use this when the user asks for a dish (e.g. "我想吃辣子鸡") rather than a restaurant.

```bash
fd search-food '辣子鸡'
```

Note: This command does not support `--json`. Parse the Rich text output.

### fd menu \<code\> --json

View a restaurant's full menu. The `code` comes from search results.

```bash
fd menu g9xw --json
```

Response:
```json
{
  "restaurant": {
    "code": "g9xw",
    "name": "Tian Tian Chicken Rice",
    "delivery_fee": 2.99,
    "min_order": 10.0
  },
  "menu": [
    {"index": 1, "name": "Steamed Chicken Rice", "price": 5.50, "category": "Signature", "product_id": 123, "variation_id": 456}
  ]
}
```

### fd add \<code\>:\<#\> [-n qty]

Add a menu item to the cart. `<#>` is the `index` from menu output.

```bash
fd add g9xw:1 -n 2    # item #1, qty 2
fd add g9xw:3          # item #3, qty 1
```

**Important:** Cart is single-restaurant. Adding from a different restaurant clears the existing cart. Warn the user before doing this.

### fd cart --json

View current cart contents.

```bash
fd cart --json
```

Response:
```json
{
  "restaurant": {"code": "g9xw", "name": "Tian Tian Chicken Rice"},
  "items": [{"name": "Steamed Chicken Rice", "price": 5.50, "quantity": 2}],
  "total": 11.00,
  "delivery_fee": 2.99
}
```

### fd clear

Clear the cart. Ask user for confirmation before running.

### fd checkout [options] --json

Place an order. **Always do `--dry-run` first and get user confirmation before the real checkout.**

**Dry run (preview):**
```bash
fd checkout --dry-run --json
```

Response:
```json
{
  "status": "dry_run",
  "order_time": "now",
  "subtotal": 11.00,
  "delivery_fee": 2.99,
  "service_fee": 0.30,
  "total": 14.29
}
```

**Place order:**
```bash
fd checkout --json
```

Response:
```json
{
  "status": "ok",
  "order_code": "a1b2-c3d4",
  "total": 14.29
}
```

#### Checkout Options

| Option | Default | Description |
|---|---|---|
| `--pay` | `balance` | Payment method (pandapay wallet) |
| `--voucher CODE` | — | Apply voucher/promo code |
| `--note 'text'` | — | Delivery instructions |
| `--time TIME` | now (immediate) | Scheduled delivery (see below) |
| `--dry-run` | — | Preview price only, don't place order |
| `--json` | — | JSON output |

#### Scheduled Delivery Time Formats

| Input | Meaning |
|---|---|
| `13:00` | Today 13:00 (tomorrow if already past) |
| `tomorrow 18:30` | Tomorrow 18:30 |
| `2026-03-15 12:00` | Specific date and time |

```bash
fd checkout --time '13:00' --json
fd checkout --time 'tomorrow 18:30' --json
```

### fd orders

View order history. No `--json` support — parse Rich text output.

### fd reorder [#]

Reorder from history.

```bash
fd reorder       # list recent orders with index numbers
fd reorder 1     # load order #1 into cart
```

### fd token [value]

Set or view login token.

### fd refresh

Auto-refresh token from Chrome cookies via Playwright.

### fd address [postal_code]

Set delivery address. No args = pick from saved account addresses interactively.

## Error Handling

Errors in JSON mode return:
```json
{"error": "错误信息"}
```

| Error | Recovery |
|---|---|
| Token 已过期 | Run `fd refresh`, or ask user for new token |
| 需要设置地址 | `fd address <postal_code>` |
| 菜品已售罄 | Show in `--dry-run`, suggest alternatives from menu |
| 购物车为空 | Need `fd add` first |
| HTTP 403 | Auto-retried internally; if persistent, try `fd refresh` |
| 无法匹配菜品 | Menu may have changed; re-run `fd menu` and re-add |

## Agent Guidelines

1. **First step is ALWAYS `fd address`** — confirm the delivery address with the user before doing anything else. If not set, ask for postal code.
2. **Always `--json`** for machine-readable output
3. **Always `--dry-run` before real checkout** — show the total and ask user to confirm
4. **Never `fd checkout` without explicit user approval** — you MUST wait for the user to say yes/confirm before running `fd checkout --json`
5. **Use `fd search-food`** when user asks for a dish name, `fd search` when they name a restaurant
6. **Present menus clearly** — group by category, show prices in SGD
7. **Hyphens = underscores** in commands (`search-food` = `search_food`)
8. **Menu indices start at 1**
9. **If user speaks Chinese**, respond in Chinese; the CLI output is in Chinese
10. **Show delivery fee + service fee** when presenting the total to avoid surprises
11. **For reorders**, always show the loaded cart and confirm before checkout
