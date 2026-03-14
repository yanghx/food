"""fd - Foodpanda CLI for Singapore (designed for AI agent usage)."""

import json as _json

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .api import FoodpandaAPI, APIError
from .config import load_config, save_config, refresh_token
from .models import Restaurant
from . import cart_store

console = Console()


def _get_api() -> FoodpandaAPI:
    config = load_config()
    return FoodpandaAPI(token=config.get("token", ""))


def _get_location() -> tuple[float, float]:
    config = load_config()
    lat = config.get("latitude", 0)
    lng = config.get("longitude", 0)
    if not lat:
        console.print("[red]请先设置地址: fd address <邮编>[/]")
        raise SystemExit(1)
    return lat, lng


def _search_vendors(api: FoodpandaAPI, query: str, lat: float, lng: float) -> list[dict]:
    """Search vendors by name, return list."""
    return api.search_restaurants(query, lat, lng)


def _find_vendor(api: FoodpandaAPI, name: str, lat: float, lng: float) -> dict | None:
    """Search for a vendor by name and return best match."""
    items = _search_vendors(api, name, lat, lng)
    if not items:
        return None
    name_lower = name.lower()
    for item in items:
        if name_lower in item.get("name", "").lower():
            return item
    return items[0]


def _load_menu(api: FoodpandaAPI, vendor_code: str, lat: float, lng: float) -> tuple[dict, list[dict]]:
    """Load vendor details and parse menu items."""
    data = api.get_vendor(vendor_code, lat, lng)
    vendor = data.get("data", data)

    rest = Restaurant(
        code=vendor_code, name=vendor.get("name", ""), cuisines="",
        rating=0, review_count=0, delivery_time="", delivery_fee=0,
        min_order=0, is_open=True,
    )
    df = vendor.get("delivery_fee")
    if df:
        rest.delivery_fee = df.get("value", 0.0) if isinstance(df, dict) else float(df)
    rest.min_order = float(vendor.get("minimum_order_amount", 0))
    rest.parse_menu(vendor)

    restaurant_info = {
        "code": vendor_code,
        "name": vendor.get("name", ""),
        "delivery_fee": rest.delivery_fee,
        "min_order": rest.min_order,
        "latitude": vendor.get("latitude", 0),
        "longitude": vendor.get("longitude", 0),
    }
    menu = [{
        "name": m.name, "price": m.price, "category": m.category,
        "description": m.description, "product_id": m.product_id,
        "variation_id": m.variation_id, "variation_code": m.variation_code,
    } for m in rest.menu_items]
    return restaurant_info, menu


def _parse_deliver_time(time_str: str) -> str:
    """Parse user-friendly time into ISO 8601 for the API.

    Accepts:
      "13:00"            → today 13:00 (or tomorrow if already past)
      "tomorrow 13:00"   → tomorrow 13:00
      "2026-03-12 13:00" → specific date
    Returns ISO 8601 string like "2026-03-12T13:00:00+08:00", or "now" if empty.
    """
    if not time_str:
        return "now"

    from datetime import datetime, timedelta, timezone

    sg_tz = timezone(timedelta(hours=8))
    now = datetime.now(sg_tz)

    time_str = time_str.strip().lower()

    # "tomorrow 13:00"
    if time_str.startswith("tomorrow"):
        t = time_str.replace("tomorrow", "").strip()
        parts = t.split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        dt = (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # "2026-03-12 13:00" or "2026-03-12T13:00"
    if len(time_str) >= 10 and time_str[4] == "-":
        time_str = time_str.replace("T", " ").replace("t", " ")
        parts = time_str.split(" ")
        date_parts = parts[0].split("-")
        y, mo, d = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
        t = parts[1] if len(parts) > 1 else "12:00"
        tp = t.split(":")
        h, m = int(tp[0]), int(tp[1]) if len(tp) > 1 else 0
        dt = datetime(y, mo, d, h, m, tzinfo=sg_tz)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # "13:00" → today or tomorrow
    parts = time_str.split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")


class UnderscoreGroup(click.Group):
    """Allow both underscores and hyphens in command names."""
    def get_command(self, ctx, cmd_name):
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        return super().get_command(ctx, cmd_name.replace("_", "-"))


@click.group(cls=UnderscoreGroup)
def cli():
    """fd - Foodpanda Singapore CLI"""
    pass


@cli.command()
@click.argument("postal_code", required=False)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON (供 AI 解析)")
@click.option("--pick", type=int, default=0, help="直接选择第 N 个已保存地址 (配合 --json)")
def address(postal_code, as_json, pick):
    """设置配送地址  无参数=从账号选择, 有参数=按邮编设置

    \b
    fd address                # 交互式选择
    fd address 123456         # 按邮编设置
    fd address --json         # JSON 列出已保存地址 + 当前地址
    fd address --json --pick 1  # 选择第 1 个已保存地址
    fd address 123456 --json  # 按邮编设置并输出 JSON
    """
    api = _get_api()
    config = load_config()

    try:
        # --json --pick N: select saved address by index without interaction
        if as_json and pick > 0 and not postal_code:
            addr_list = _fetch_saved_addresses(api)
            idx = pick - 1
            if not (0 <= idx < len(addr_list)):
                console.print(_json.dumps({"error": f"无效编号 {pick}, 共 {len(addr_list)} 个地址"}, ensure_ascii=False))
                return
            a = addr_list[idx]
            config.update({
                "latitude": float(a.get("latitude", 0)),
                "longitude": float(a.get("longitude", 0)),
                "address": a.get("formatted_customer_address") or a.get("address_line1", ""),
                "postal_code": str(a.get("postcode", "")),
            })
            save_config(config)
            console.print(_json.dumps({
                "status": "ok",
                "address": config["address"],
                "postal_code": config["postal_code"],
                "latitude": config["latitude"],
                "longitude": config["longitude"],
            }, ensure_ascii=False, indent=2))
            return

        # No postal code provided
        if not postal_code:
            current = config.get("address", "")

            if as_json:
                # JSON mode: list saved addresses + current, no interaction
                result = {"current": None, "saved_addresses": []}
                if current:
                    result["current"] = {
                        "address": current,
                        "postal_code": config.get("postal_code", ""),
                        "latitude": config.get("latitude", 0),
                        "longitude": config.get("longitude", 0),
                    }
                if config.get("token"):
                    try:
                        addr_list = _fetch_saved_addresses(api)
                        result["saved_addresses"] = [
                            {
                                "index": i,
                                "address": a.get("formatted_customer_address") or a.get("address_line1", ""),
                                "label": a.get("label") or a.get("delivery_instructions") or "",
                                "postal_code": str(a.get("postcode", "")),
                                "latitude": float(a.get("latitude", 0)),
                                "longitude": float(a.get("longitude", 0)),
                                "id": a.get("id", ""),
                            }
                            for i, a in enumerate(addr_list, 1)
                        ]
                    except APIError as e:
                        result["error"] = str(e)
                console.print(_json.dumps(result, ensure_ascii=False, indent=2))
                return

            # Interactive mode
            if current:
                console.print(f"[dim]当前地址: {current}[/]\n")

            if config.get("token"):
                console.print("[blue]正在获取账号保存的地址...[/]")
                try:
                    addr_list = _fetch_saved_addresses(api)
                    if addr_list:
                        for i, addr in enumerate(addr_list, 1):
                            label = addr.get("label") or addr.get("delivery_instructions") or ""
                            address_str = addr.get("formatted_customer_address") or addr.get("address_line1", "")
                            tag = f" ({label})" if label else ""
                            console.print(f"[{i}] {address_str}{tag}")
                        console.print("[0] 手动输入邮编")
                        choice = console.input("\n[green]选择> [/]").strip()
                        if choice != "0":
                            idx = int(choice) - 1
                            if 0 <= idx < len(addr_list):
                                a = addr_list[idx]
                                config.update({
                                    "latitude": float(a.get("latitude", 0)),
                                    "longitude": float(a.get("longitude", 0)),
                                    "address": a.get("formatted_customer_address") or a.get("address_line1", ""),
                                    "postal_code": str(a.get("postcode", "")),
                                })
                                save_config(config)
                                console.print(f"[green]✓ 地址已设置: {config['address']}[/]")
                                return
                    else:
                        console.print("[dim]账号无保存地址[/]")
                except APIError as e:
                    console.print(f"[yellow]⚠ {e}[/]")

            postal_code = console.input("[green]请输入邮编> [/]").strip()
            if not postal_code:
                return

        result = api.resolve_postal_code(postal_code)
        if not result:
            if as_json:
                console.print(_json.dumps({"error": f"未找到邮编: {postal_code}"}, ensure_ascii=False))
            else:
                console.print("[red]未找到该邮编[/]")
            return
        config.update({
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "address": result["address"],
            "postal_code": postal_code,
        })
        save_config(config)
        if as_json:
            console.print(_json.dumps({
                "status": "ok",
                "address": result["address"],
                "postal_code": postal_code,
                "latitude": result["latitude"],
                "longitude": result["longitude"],
            }, ensure_ascii=False, indent=2))
        else:
            console.print(f"[green]✓ 地址已设置: {result['address']}[/]")
    except EOFError:
        if as_json:
            console.print(_json.dumps({"error": "非交互终端，请传入邮编: fd address <postal_code> --json"}, ensure_ascii=False))
        else:
            console.print("\n[yellow]非交互终端，请直接传入邮编: fd address <postal_code>[/]")
    except (APIError, ValueError, IndexError) as e:
        if as_json:
            console.print(_json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


def _fetch_saved_addresses(api: FoodpandaAPI) -> list[dict]:
    """Fetch saved addresses from API, normalizing the response format."""
    result = api.get_saved_addresses()
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        addr_list = result.get("items") or result.get("addresses") or result.get("data", [])
        return addr_list if isinstance(addr_list, list) else []
    return []


def _print_token_expiry(tok: str):
    """Print token expiry info."""
    try:
        import base64, time, datetime
        payload = _json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
        exp = datetime.datetime.fromtimestamp(payload["expires"])
        remaining = payload["expires"] - time.time()
        if remaining > 0:
            h, m = int(remaining // 3600), int((remaining % 3600) // 60)
            console.print(f"[green]过期时间: {exp.strftime('%Y-%m-%d %H:%M')}  (剩余 {h}h{m}m)[/]")
        else:
            console.print(f"[red]已过期: {exp.strftime('%Y-%m-%d %H:%M')}[/]")
    except Exception:
        pass


@cli.command()
@click.argument("token_value", required=False)
def token(token_value):
    """设置登录 Token  例: fd token eyJhbG..."""
    config = load_config()
    if token_value:
        config["token"] = token_value
        save_config(config)
        console.print("[green]✓ Token 已保存[/]")
    else:
        current = config.get("token", "")
        if current:
            console.print(f"[dim]当前 Token: {current[:20]}...{current[-10:]}[/]")
            _print_token_expiry(current)
        else:
            console.print("[dim]未设置 Token[/]")
        console.print("[dim]设置: fd token <value>  |  续期: fd refresh[/]")


@cli.command()
def refresh():
    """自动续期 Token — 从 Chrome cookie 读取或触发 Chrome 刷新"""
    console.print("[blue]正在刷新 token...[/]")
    new_token = refresh_token()
    if new_token:
        console.print("[green]✓ Token 已刷新[/]")
        _print_token_expiry(new_token)
    else:
        error = getattr(refresh_token, "last_error", "")
        if error:
            console.print(f"[red]✗ {error}[/]")
        else:
            console.print("[red]✗ 刷新失败[/]")
        console.print("[dim]确保 Chrome 已登录 foodpanda.sg[/]")
        console.print("[dim]或手动设置: fd token <value>[/]")


@cli.command()
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON")
def search(name, as_json):
    """搜索餐厅  例: fd search 'chicken rice'"""
    api = _get_api()
    lat, lng = _get_location()
    try:
        items = _search_vendors(api, name, lat, lng)
        if not items:
            if as_json:
                console.print(_json.dumps({"results": []}, ensure_ascii=False))
            else:
                console.print("[dim]未找到结果[/]")
            return

        if as_json:
            results = [{"index": i+1, "name": v.get("name", ""), "code": v.get("code", ""),
                        "rating": v.get("rating", 0)} for i, v in enumerate(items[:15])]
            console.print(_json.dumps({"results": results}, ensure_ascii=False, indent=2))
            return

        table = Table(title=f"搜索: {name}", box=box.ROUNDED, border_style="cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("餐厅", style="bold", min_width=25)
        table.add_column("评分", style="green", width=6)
        table.add_column("Code", style="dim", width=6)

        for i, item in enumerate(items[:15], 1):
            rating = item.get("rating", 0)
            table.add_row(
                str(i), item.get("name", ""),
                f"{rating:.1f}" if rating else "-",
                item.get("code", ""),
            )
        console.print(table)
        console.print(f"\n[dim]查看菜单: fd menu <code>  |  添加: fd add 代码:编号[/]")
    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


@cli.command()
@click.argument("food_name")
def search_food(food_name):
    """搜索菜品  例: fd search_food '辣子鸡'"""
    api = _get_api()
    lat, lng = _get_location()
    try:
        items = _search_vendors(api, food_name, lat, lng)
        if not items:
            console.print("[dim]未找到结果[/]")
            return

        table = Table(title=f"搜索菜品: {food_name}", box=box.ROUNDED, border_style="cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("餐厅", style="bold", min_width=25)
        table.add_column("评分", style="green", width=6)
        table.add_column("Code", style="dim", width=6)

        for i, item in enumerate(items[:15], 1):
            rating = item.get("rating", 0)
            table.add_row(
                str(i), item.get("name", ""),
                f"{rating:.1f}" if rating else "-",
                item.get("code", ""),
            )
        console.print(table)

        # Also try to show matching menu items from top results
        console.print(f"\n[blue]正在查找含 \"{food_name}\" 的菜品...[/]")
        found_any = False
        for vendor in items[:3]:
            code = vendor.get("code", "")
            if not code:
                continue
            try:
                _, menu = _load_menu(api, code, lat, lng)
                matches = [m for m in menu if food_name.lower() in m["name"].lower()]
                if matches:
                    found_any = True
                    console.print(f"\n[bold cyan]{vendor.get('name', '')}[/]")
                    for m in matches[:5]:
                        console.print(f"  ${m['price']:.2f}  {m['name']}")
                    console.print(f"  [dim]→ fd menu {code}  然后 fd add {code}:编号[/]")
            except APIError:
                continue
        if not found_any:
            console.print("[dim]未在前几家餐厅的菜单中找到精确匹配[/]")
    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


@cli.command()
@click.argument("menu_code")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON")
def menu(menu_code, as_json):
    """查看餐厅菜单  例: fd menu owiq"""
    api = _get_api()
    lat, lng = _get_location()
    try:
        restaurant_info, items = _load_menu(api, menu_code, lat, lng)

        if as_json:
            console.print(_json.dumps({
                "restaurant": restaurant_info,
                "menu": [{"index": i+1, **item} for i, item in enumerate(items)],
            }, ensure_ascii=False, indent=2))
            return

        console.print(f"\n[bold]{restaurant_info['name']}[/]  配送费: ${restaurant_info['delivery_fee']:.2f}  起送: ${restaurant_info['min_order']:.2f}")

        table = Table(box=box.SIMPLE_HEAVY, border_style="cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("菜品", style="bold", min_width=25)
        table.add_column("价格", style="green", justify="right", width=8)

        current_cat = ""
        for i, item in enumerate(items, 1):
            if item["category"] != current_cat:
                current_cat = item["category"]
                table.add_row("", f"[yellow]── {current_cat} ──[/]", "")
            table.add_row(str(i), item["name"], f"${item['price']:.2f}")

        console.print(table)
        console.print(f"\n[dim]添加: fd add {menu_code}:编号  例: fd add {menu_code}:1[/]")
    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


@cli.command()
@click.argument("spec")
@click.option("-n", "--qty", default=1, help="数量")
def add(spec, qty):
    """加入购物车  例: fd add g9xw:3 -n 2  (餐厅代码:菜品编号)"""
    if ":" not in spec:
        console.print("[red]格式: 餐厅代码:菜品编号  例: fd add g9xw:3[/]")
        console.print("[dim]先用 fd search 或 fd menu 查看代码和编号[/]")
        return

    vendor_code, food_id = spec.split(":", 1)
    vendor_code = vendor_code.strip()
    food_id = food_id.strip()

    api = _get_api()
    lat, lng = _get_location()

    try:
        restaurant_info, menu_items = _load_menu(api, vendor_code, lat, lng)

        # Find item by number index
        try:
            idx = int(food_id) - 1
            if not (0 <= idx < len(menu_items)):
                console.print(f"[red]✗ 菜品编号 {food_id} 超出范围 (1-{len(menu_items)})[/]")
                console.print(f"[dim]查看菜单: fd menu {vendor_code}[/]")
                return
            item = menu_items[idx]
        except ValueError:
            # Fallback: treat as name search
            food_lower = food_id.lower()
            matches = [m for m in menu_items if food_lower in m["name"].lower()]
            if not matches:
                words = food_lower.split()
                matches = [m for m in menu_items if all(w in m["name"].lower() for w in words)]
            if not matches:
                console.print(f"[red]✗ 未找到菜品: {food_id}[/]")
                console.print(f"[dim]查看菜单: fd menu {vendor_code}[/]")
                return
            item = matches[0]

        cart = cart_store.add_item(restaurant_info, item, qty)
        total = cart_store.get_total(cart)

        console.print(f"[green]✓ 已加入: {item['name']} x{qty}  ${item['price'] * qty:.2f}[/]")
        console.print(f"[dim]  购物车: {len(cart['items'])} 件商品  合计 ${total:.2f}[/]")
    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="输出 JSON")
def cart(as_json):
    """查看购物车"""
    data = cart_store.load_cart()
    if not data["items"]:
        if as_json:
            console.print(_json.dumps({"items": [], "total": 0}, ensure_ascii=False))
        else:
            console.print("[dim]购物车为空[/]")
        return

    if as_json:
        console.print(_json.dumps({
            "restaurant": data["restaurant"],
            "items": data["items"],
            "total": cart_store.get_total(data),
            "delivery_fee": cart_store.get_delivery_fee(data),
        }, ensure_ascii=False, indent=2))
        return

    rest = data["restaurant"]
    table = Table(title=f"购物车 - {rest['name']}", box=box.ROUNDED, border_style="yellow")
    table.add_column("菜品", style="bold", min_width=25)
    table.add_column("单价", style="green", justify="right")
    table.add_column("数量", style="cyan", justify="center")
    table.add_column("小计", style="bold green", justify="right")

    for item in data["items"]:
        subtotal = item["price"] * item["quantity"]
        table.add_row(item["name"], f"${item['price']:.2f}", str(item["quantity"]), f"${subtotal:.2f}")

    total = cart_store.get_total(data)
    fee = cart_store.get_delivery_fee(data)
    table.add_section()
    table.add_row("[bold]合计[/]", "", "", f"[bold]${total:.2f}[/]")
    table.add_row("配送费", "", "", f"${fee:.2f}")
    table.add_row("[bold yellow]总计[/]", "", "", f"[bold yellow]${total + fee:.2f}[/]")

    console.print(table)
    console.print(f"\n[dim]下单: fd checkout  |  清空: fd clear[/]")


@cli.command()
def clear():
    """清空购物车"""
    cart_store.clear_cart()
    console.print("[green]✓ 购物车已清空[/]")


@cli.command()
@click.option("--pay", default="balance", help="支付方式: balance (pandapay) / 其他")
@click.option("--voucher", default="", help="优惠券码")
@click.option("--note", default="", help="配送备注")
@click.option("--time", "deliver_time", default="", help="定时配送: 13:00 / 'tomorrow 13:00' / '2026-03-12 13:00'")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON 格式 (供 AI 解析)")
@click.option("--dry-run", is_flag=True, help="只计算价格, 不下单")
def checkout(pay, voucher, note, deliver_time, as_json, dry_run):
    """纯 API 下单: cart/calculate → purchase/intent → cart/checkout

    \b
    完整流程:
      fd add g9xw:3 -n 2              # 添加菜品到本地购物车
      fd checkout --dry-run            # 计算服务端真实价格 (不下单)
      fd checkout                      # 立即下单 (默认 pandapay)
      fd checkout --time 13:00         # 定时配送 (今天/明天 13:00)
      fd checkout --time 'tomorrow 18:30'  # 明天 18:30 配送
    """
    data = cart_store.load_cart()
    if not data["items"]:
        _checkout_error("购物车为空，先用 fd add 添加菜品", as_json)
        return

    rest = data["restaurant"]
    config = load_config()
    token = config.get("token", "")
    lat = config.get("latitude", 0)
    lng = config.get("longitude", 0)
    postcode = config.get("postal_code", "")
    order_time = _parse_deliver_time(deliver_time)

    if not token:
        _checkout_error("需要登录 Token: fd token <value>", as_json)
        return
    if not lat:
        _checkout_error("需要设置地址: fd address <邮编>", as_json)
        return

    api = _get_api()
    try:
        # Fetch delivery address early — address_id is needed for cart/calculate
        addresses = api.get_saved_addresses()
        addr_list = addresses.get("items", []) if isinstance(addresses, dict) else addresses if isinstance(addresses, list) else []
        address = None
        for a in addr_list:
            if str(a.get("postcode", "")) == postcode:
                address = a
                break
        if not address and addr_list:
            address = addr_list[0]
        address_id = str(address.get("id", "")) if address else ""
        if address:
            postcode = str(address.get("postcode", postcode))

        # Step 1: Resolve product IDs from fresh menu
        if not as_json:
            console.print("[blue]  [1/4] 解析菜品 ID...[/]")
        rest_info, fresh_menu = _load_menu(api, rest["code"], lat, lng)
        vendor_lat = rest_info.get("latitude", 0)
        vendor_lng = rest_info.get("longitude", 0)

        products_for_api = []
        unmatched = []
        for item in data["items"]:
            matched = _match_cart_item(item, fresh_menu)
            if matched:
                products_for_api.append({
                    "id": matched["product_id"],
                    "variation_id": matched["variation_id"],
                    "code": matched.get("variation_code", ""),
                    "variation_code": matched.get("variation_code", ""),
                    "quantity": item["quantity"],
                    "price": matched["price"],
                    "original_price": matched["price"],
                    "toppings": [],
                    "sold_out_option": "REFUND",
                    "special_instructions": "",
                })
            else:
                unmatched.append(item["name"])

        if unmatched:
            msg = f"无法匹配菜品: {', '.join(unmatched)}。请 fd menu {rest['code']} 重新查看"
            if not products_for_api:
                _checkout_error(msg, as_json)
                return
            if not as_json:
                console.print(f"[yellow]  ⚠ {msg}[/]")

        # Step 2: cart/calculate — get server-side pricing
        if not as_json:
            console.print("[blue]  [2/4] 计算价格 (cart/calculate)...[/]")
        calc = api.cart_calculate(
            vendor_code=rest["code"],
            products=products_for_api,
            latitude=lat,
            longitude=lng,
            vendor_latitude=vendor_lat,
            vendor_longitude=vendor_lng,
            address_id=address_id,
            postcode=postcode,
            voucher=voucher,
            delivery_instructions=note,
            order_time=order_time,
        )

        # Extract pricing from server response (use server totals, not manual sum)
        calc_products = calc.get("products", [])
        payment = calc.get("payment", {})
        subtotal = payment.get("subtotal", 0)
        selected_option = calc.get("expedition", {}).get("selected_delivery_option", {})
        delivery_fee = selected_option.get("delivery_fee", 0)
        delivery_fee_original = selected_option.get("delivery_fee_without_discount", delivery_fee)
        delivery_fee_discount = selected_option.get("delivery_fee_discount", 0)
        service_fee = payment.get("service_fee", 0)
        total = payment.get("payable_total", 0)
        # payment_limits are needed for purchase intent
        payment_limits = calc.get("payment_limits", [])
        food_subtotal = subtotal  # for purchase intent
        for pl in payment_limits:
            if pl.get("limit_code") == "foodafterdiscount":
                food_subtotal = pl["limit_amount"]

        if not as_json:
            if order_time != "now":
                console.print(f"[cyan]  定时配送: {order_time}[/]")
            console.print(f"[green]  ✓ 服务端价格:[/]")
            for i, p in enumerate(calc_products):
                available = "[green]✓[/]" if p.get("is_available", True) else "[red]✗ 已售罄[/]"
                name = (p.get("variation_name") or data["items"][i]["name"]) if i < len(data["items"]) else "?"
                console.print(f"    {name} x{p.get('quantity',1)} ${p.get('price',0):.2f} {available}")
            if delivery_fee_discount:
                console.print(f"    小计: ${subtotal:.2f}  配送费: [strike]${delivery_fee_original:.2f}[/] ${delivery_fee:.2f} (省${delivery_fee_discount:.2f})  服务费: ${service_fee:.2f}")
            else:
                console.print(f"    小计: ${subtotal:.2f}  配送费: ${delivery_fee:.2f}  服务费: ${service_fee:.2f}")
            console.print(f"    [bold]总计: ${total:.2f}[/]")

        if dry_run:
            if as_json:
                console.print(_json.dumps({
                    "status": "dry_run",
                    "order_time": order_time,
                    "restaurant": rest,
                    "products": calc_products,
                    "subtotal": subtotal,
                    "delivery_fee": delivery_fee,
                    "service_fee": service_fee,
                    "total": total,
                    "unmatched": unmatched,
                    "server_response": calc,
                }, ensure_ascii=False, indent=2))
            else:
                console.print("[dim]  dry-run 完成。执行 fd checkout 正式下单[/]")
            return

        # Check availability
        unavailable = [p for p in calc_products if not p.get("is_available", True)]
        if unavailable:
            names = ", ".join(p.get("variation_name", "?") for p in unavailable)
            _checkout_error(f"以下菜品已售罄: {names}", as_json)
            return

        # Step 3: purchase/intent → confirm
        if not as_json:
            console.print(f"[blue]  [3/4] 创建支付意向...[/]")

        intent = api.create_purchase_intent(rest["code"], food_subtotal, total)
        intent_data = intent.get("data", intent)
        intent_id = intent_data.get("purchaseIntent", {}).get("id", "")

        if not intent_id:
            _checkout_error(f"创建支付意向失败: {_json.dumps(intent_data, ensure_ascii=False)[:200]}", as_json)
            return

        api.confirm_purchase_intent(intent_id, rest["code"], food_subtotal, total, pay)

        # Step 4: cart/checkout — actually place the order
        if not as_json:
            console.print(f"[blue]  [4/4] 提交订单 (支付: {pay})...[/]")

        # Get customer info for checkout (cache in config to survive 403)
        customer_id = config.get("customer_id", "")
        customer_email = config.get("customer_email", "")
        try:
            customer = api.get_customer_info()
            customer_data = customer.get("data", customer)
            customer_id = str(customer_data.get("id", ""))
            customer_email = customer_data.get("email", "")
            config["customer_id"] = customer_id
            config["customer_email"] = customer_email
            save_config(config)
        except APIError:
            if not customer_id:
                _checkout_error("获取客户信息失败且无缓存，请重试", as_json)
                return

        if not address:
            _checkout_error("未找到配送地址，请先 fd address 设置", as_json)
            return

        # Merge calc_products with local product info for checkout
        checkout_products = []
        for i, cp in enumerate(calc_products):
            product = {**cp}
            # Add fields from our original products_for_api that calc response may lack
            if i < len(products_for_api):
                src = products_for_api[i]
                product.setdefault("code", src.get("code", ""))
                product.setdefault("variation_code", src.get("variation_code", ""))
            # Add name from local cart if missing
            if not product.get("name") and i < len(data["items"]):
                product["name"] = data["items"][i]["name"]
                product["description"] = data["items"][i]["name"]
            product.setdefault("sold_out_option", "REFUND")
            product.setdefault("toppings", [])
            product.setdefault("special_instructions", "")
            checkout_products.append(product)

        result = api.cart_checkout(
            vendor_code=rest["code"],
            products=checkout_products,
            purchase_intent_id=intent_id,
            expected_total=total,
            customer_id=customer_id,
            customer_email=customer_email,
            address=address,
            latitude=lat,
            longitude=lng,
            payment_method=pay,
            delivery_instructions=note,
            voucher=voucher,
            order_time=order_time,
        )

        # Extract order code from response
        result_data = result.get("data", result)
        order_items = result_data.get("items", [])
        order_code = ""
        if order_items:
            order_code = order_items[0].get("order_code", "")

        if as_json:
            console.print(_json.dumps({
                "status": "ok",
                "order_code": order_code,
                "intent_id": intent_id,
                "total": total,
            }, ensure_ascii=False, indent=2))
        else:
            console.print(f"[green]  ✓ 下单成功![/]")
            if order_code:
                console.print(f"[green]  订单号: {order_code}[/]")
            console.print(f"[green]  总计: ${total:.2f}[/]")

        cart_store.clear_cart()
        if not as_json:
            console.print("[dim]  购物车已清空[/]")

    except APIError as e:
        _checkout_error(str(e), as_json)
    finally:
        api.close()


def _match_cart_item(item: dict, fresh_menu: list[dict]) -> dict | None:
    """Match a local cart item to a fresh menu item by variation_id or name."""
    vid = item.get("variation_id", 0)
    pid = item.get("product_id", 0)
    if vid and pid:
        m = next((m for m in fresh_menu if m["variation_id"] == vid), None)
        if m:
            return m
    m = next((m for m in fresh_menu if m["name"] == item["name"]), None)
    if m and m.get("variation_id"):
        return m
    name_lower = item["name"].lower()
    m = next((m for m in fresh_menu if name_lower in m["name"].lower() and m.get("variation_id")), None)
    return m


def _checkout_error(msg: str, as_json: bool):
    if as_json:
        console.print(_json.dumps({"error": msg}, ensure_ascii=False))
    else:
        console.print(f"[red]✗ {msg}[/]")


@cli.command()
def orders():
    """查看订单历史"""
    api = _get_api()
    try:
        data = api.get_order_history()
        items = data.get("data", {}).get("items", [])
        if not items:
            console.print("[dim]暂无订单[/]")
            return

        table = Table(title="订单历史", box=box.ROUNDED, border_style="green")
        table.add_column("餐厅", style="bold", min_width=25)
        table.add_column("金额", style="green", justify="right")
        table.add_column("状态", width=8)
        table.add_column("日期", style="dim")

        for order in items[:15]:
            vendor = order.get("vendor", {})
            status = order.get("current_status", {})
            status_type = status.get("type", "")
            status_str = "[green]已送达[/]" if status_type == "final" else "[yellow]进行中[/]"
            date = order.get("ordered_at", {}).get("date", "")[:10]
            table.add_row(vendor.get("name", ""), f"${order.get('total_value', 0):.2f}", status_str, date)

        console.print(table)
    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()


@cli.command()
@click.argument("order_index", type=int, default=0)
def reorder(order_index):
    """再来一单 - 从历史订单加入购物车, 再 fd checkout

    \b
    fd reorder       # 列出最近订单
    fd reorder 1     # 把第1个历史订单的菜品加入购物车
    """
    api = _get_api()
    lat, lng = _get_location()
    try:
        data = api.get_order_history()
        items = data.get("data", {}).get("items", [])
        if not items:
            console.print("[dim]暂无订单[/]")
            return

        if order_index == 0:
            # Just list orders
            for i, order in enumerate(items[:10], 1):
                vendor = order.get("vendor", {})
                products = order.get("order_products", [])
                names = ", ".join(p.get("name", "")[:20] for p in products[:3])
                date = order.get("ordered_at", {}).get("date", "")[:10]
                console.print(f"[{i}] [bold]{vendor.get('name', '')}[/]  ${order.get('total_value', 0):.2f}  {date}")
                if names:
                    console.print(f"    [dim]{names}[/]")
            console.print(f"\n[dim]重新下单: fd reorder <编号>  例: fd reorder 1[/]")
            return

        idx = order_index - 1
        if not (0 <= idx < len(items[:10])):
            console.print("[red]无效编号[/]")
            return

        order = items[idx]
        vendor = order.get("vendor", {})
        vendor_code = vendor.get("code", "")
        if not vendor_code:
            console.print("[red]无法获取餐厅代码[/]")
            return

        # Load menu to match products
        console.print(f"[blue]正在加载 {vendor.get('name', '')} 的菜单...[/]")
        restaurant_info, menu_items = _load_menu(api, vendor_code, lat, lng)

        # Clear cart and add items from order
        cart_store.clear_cart()
        order_products = order.get("order_products", [])
        added = 0
        for op in order_products:
            op_name = op.get("name", "")
            qty = op.get("quantity", 1)
            matched = next((m for m in menu_items if m["name"] == op_name), None)
            if not matched:
                name_lower = op_name.lower()
                matched = next((m for m in menu_items if name_lower in m["name"].lower()), None)
            if matched:
                cart_store.add_item(restaurant_info, matched, qty)
                added += 1
                console.print(f"  [green]✓[/] {matched['name']} x{qty}")
            else:
                console.print(f"  [yellow]✗[/] {op_name} (菜单中未找到)")

        if added:
            console.print(f"\n[green]✓ 已加入 {added} 件菜品到购物车[/]")
            console.print("[dim]下单: fd checkout[/]")
        else:
            console.print("[red]未能匹配到任何菜品[/]")

    except APIError as e:
        console.print(f"[red]✗ {e}[/]")
    finally:
        api.close()
