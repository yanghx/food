"""Persistent cart storage between CLI invocations."""

import json
import os

from .config import CONFIG_DIR

CART_FILE = os.path.join(CONFIG_DIR, "cart.json")


def load_cart() -> dict:
    """Load cart from disk. Returns {restaurant: {...}, items: [...]}"""
    if os.path.exists(CART_FILE):
        with open(CART_FILE) as f:
            return json.load(f)
    return {"restaurant": None, "items": []}


def save_cart(cart: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CART_FILE, "w") as f:
        json.dump(cart, f, indent=2, ensure_ascii=False)


def add_item(restaurant: dict, item: dict, quantity: int = 1):
    """Add an item to the persisted cart."""
    cart = load_cart()

    # If different restaurant, clear cart
    if cart["restaurant"] and cart["restaurant"]["code"] != restaurant["code"]:
        cart = {"restaurant": None, "items": []}

    cart["restaurant"] = restaurant

    # Check if item already in cart
    for existing in cart["items"]:
        if existing["name"] == item["name"]:
            existing["quantity"] += quantity
            save_cart(cart)
            return cart

    cart["items"].append({
        "name": item["name"],
        "price": item["price"],
        "quantity": quantity,
        "product_id": item.get("product_id", 0),
        "variation_id": item.get("variation_id", 0),
        "variation_code": item.get("variation_code", ""),
    })
    save_cart(cart)
    return cart


def clear_cart():
    save_cart({"restaurant": None, "items": []})


def get_total(cart: dict) -> float:
    return sum(i["price"] * i["quantity"] for i in cart["items"])


def get_delivery_fee(cart: dict) -> float:
    if cart["restaurant"]:
        return cart["restaurant"].get("delivery_fee", 0)
    return 0
