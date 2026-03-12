# fd — AI Agent Skill Guide

This document describes how an AI agent (e.g. Claude) can use the `fd` CLI to order food on Foodpanda Singapore on behalf of a user.

## Prerequisites

Before using `fd`, ensure:
1. Token is set: `fd token` to check, `fd refresh` to auto-refresh from Chrome
2. Address is set: `fd address` to check/set

## Workflow

### Standard Order Flow

```
fd search '<query>'          # find restaurant
fd menu <code>               # browse menu
fd add <code>:<#> [-n qty]   # add items to cart
fd cart --json               # verify cart
fd checkout --dry-run --json # preview total
fd checkout --json           # place order
```

### Reorder Flow

```
fd reorder                   # list recent orders
fd reorder <#>               # load order into cart
fd checkout --json           # place order
```

## Command Reference for Agents

All commands below support `--json` where noted, producing structured output suitable for parsing.

### Search (`--json`)

```bash
fd search 'chicken rice' --json
```

```json
{
  "results": [
    {"index": 1, "name": "Tian Tian Chicken Rice", "code": "g9xw", "rating": 4.5}
  ]
}
```

### Menu (`--json`)

```bash
fd menu g9xw --json
```

```json
{
  "restaurant": {"code": "g9xw", "name": "...", "delivery_fee": 2.99, "min_order": 10.0},
  "menu": [
    {"index": 1, "name": "Chicken Rice", "price": 5.50, "category": "Mains", "product_id": 123, "variation_id": 456}
  ]
}
```

### Add to Cart

```bash
fd add g9xw:1 -n 2    # item #1, qty 2
fd add g9xw:3          # item #3, qty 1
```

Items are identified by `<restaurant_code>:<menu_index>` where the index comes from `fd menu`.

### Cart (`--json`)

```bash
fd cart --json
```

```json
{
  "restaurant": {"code": "g9xw", "name": "..."},
  "items": [{"name": "Chicken Rice", "price": 5.50, "quantity": 2}],
  "total": 11.00,
  "delivery_fee": 2.99
}
```

### Checkout (`--json`)

**Dry run** (preview price, no order placed):

```bash
fd checkout --dry-run --json
```

```json
{
  "status": "dry_run",
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

```json
{
  "status": "ok",
  "order_code": "a1b2-c3d4",
  "total": 14.29
}
```

**Scheduled delivery:**

```bash
fd checkout --time '13:00' --json          # today 13:00 (or tomorrow if past)
fd checkout --time 'tomorrow 18:30' --json # tomorrow 18:30
fd checkout --time '2026-03-15 12:00' --json
```

### Checkout Options

| Option | Default | Description |
|---|---|---|
| `--pay` | `balance` | Payment method (pandapay wallet) |
| `--voucher` | (none) | Voucher code |
| `--note` | (none) | Delivery instructions |
| `--time` | now | Scheduled delivery time |
| `--dry-run` | false | Calculate only, don't order |
| `--json` | false | JSON output |

## Error Handling

Errors are returned as:

```json
{"error": "Token 已过期，请重新设置"}
```

Common errors and recovery:
- **Token expired** → `fd refresh` or ask user for new token
- **No address** → `fd address <postal_code>`
- **Item sold out** → shown in `--dry-run`, remove and pick alternative
- **Cart empty** → `fd add` items first
- **HTTP 403** → auto-retried (PerimeterX), usually resolves

## Tips for Agents

1. **Always use `--json`** for parseable output
2. **Always `--dry-run` before checkout** to confirm price with the user
3. **Use `fd search-food`** when the user asks for a dish rather than a restaurant
4. **Cart is single-restaurant** — adding items from a different restaurant clears the cart
5. **Menu indices start at 1** and match the `index` field in JSON output
6. **Hyphens and underscores are interchangeable** in command names (`search-food` = `search_food`)
