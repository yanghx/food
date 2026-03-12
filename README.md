# foodpanda — Claude Code Skill

A Claude Code skill for ordering food on [Foodpanda Singapore](https://www.foodpanda.sg). Install this skill, then use `/foodpanda` or let the agent automatically handle food ordering requests.

## Install

Copy (or symlink) this repo into your Claude Code skills directory:

```bash
# Option 1: Clone directly
git clone <repo-url> ~/.claude/skills/foodpanda

# Option 2: Symlink an existing checkout
ln -s /path/to/this/repo ~/.claude/skills/foodpanda
```

Then install the CLI:

```bash
bash ~/.claude/skills/foodpanda/scripts/install.sh
```

This creates a virtualenv in `scripts/.venv`, installs dependencies (`rich`, `httpx`, `click`, `playwright`, `browser-cookie3`), and places the `fd` command at `~/.local/bin/fd`.

Make sure `~/.local/bin` is in your `PATH`.

## Setup

```bash
# Set your Foodpanda token (from browser cookies)
fd token eyJhbG...

# Or auto-refresh from Chrome
fd refresh

# Set delivery address
fd address 123456
```

## Usage

Invoke the skill in Claude Code:

```
/foodpanda 帮我搜一下附近的鸡饭
/foodpanda search sushi
/foodpanda reorder last meal
```

Or just ask naturally — the agent will auto-invoke when you talk about ordering food.

### Example Conversation

```
You: 帮我点一份海南鸡饭
Agent: [searches restaurants, shows options]
Agent: [shows menu, asks what to add]
Agent: [adds to cart, shows dry-run total]
Agent: 总计 $14.29 (含配送费 $2.99)，确认下单吗？
You: 好
Agent: [places order] ✓ 订单号: a1b2-c3d4
```

## Project Structure

```
foodpanda/                          # ← this is the skill root
├── SKILL.md                        # Skill definition (frontmatter + agent instructions)
├── README.md                       # This file
├── scripts/
│   ├── install.sh                  # One-command installer
│   ├── setup.py                    # Python package setup
│   ├── requirements.txt
│   └── foodpanda/                  # Python package
│       ├── __init__.py
│       ├── cli.py                  # Click commands & Rich UI
│       ├── api.py                  # FoodpandaAPI (all HTTP calls)
│       ├── models.py               # Restaurant, MenuItem dataclasses
│       ├── cart_store.py            # Persistent cart (JSON)
│       └── config.py               # Config & token refresh
```

## Commands

| Command | Description |
|---|---|
| `fd address [postal]` | Set delivery address |
| `fd token [value]` | Set or view login token |
| `fd refresh` | Auto-refresh token from Chrome cookies |
| `fd search <name>` | Search restaurants |
| `fd search-food <name>` | Search dishes across restaurants |
| `fd menu <code>` | View restaurant menu |
| `fd add <code>:<#> [-n qty]` | Add item to cart |
| `fd cart` | View cart |
| `fd clear` | Clear cart |
| `fd checkout` | Place order |
| `fd orders` | View order history |
| `fd reorder [#]` | Re-order from history |

Most commands support `--json` for machine-readable output.

## Requirements

- Python 3.12+
- Chrome (for auto token refresh)
- A Foodpanda Singapore account
