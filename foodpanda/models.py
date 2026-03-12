from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MenuItem:
    id: int
    name: str
    price: float
    description: str
    category: str
    product_id: int = 0
    variation_id: int = 0
    variation_code: str = ""


@dataclass
class Restaurant:
    code: str
    name: str
    cuisines: str
    rating: float
    review_count: int
    delivery_time: str
    delivery_fee: float
    min_order: float
    is_open: bool
    menu_items: list[MenuItem] = field(default_factory=list)

    @staticmethod
    def from_api(vendor: dict) -> Restaurant:
        cuisines = ", ".join(c.get("name", "") for c in vendor.get("cuisines", []))
        delivery_fee = 0.0
        if vendor.get("delivery_fee"):
            delivery_fee = vendor["delivery_fee"].get("value", 0.0) if isinstance(vendor["delivery_fee"], dict) else float(vendor["delivery_fee"])
        min_order = 0.0
        if vendor.get("minimum_order_amount"):
            min_order = float(vendor["minimum_order_amount"])
        delivery_time = ""
        dt = vendor.get("delivery_time")
        if dt:
            delivery_time = f"{dt} min" if isinstance(dt, (int, float)) else str(dt)

        return Restaurant(
            code=vendor.get("code", ""),
            name=vendor.get("name", ""),
            cuisines=cuisines,
            rating=vendor.get("rating", 0.0),
            review_count=vendor.get("review_number", 0),
            delivery_time=delivery_time,
            delivery_fee=delivery_fee,
            min_order=min_order,
            is_open=vendor.get("is_active", False),
        )

    def parse_menu(self, vendor_data: dict):
        """Parse menu from vendor detail API response."""
        self.menu_items.clear()
        menus = vendor_data.get("menus", [])
        item_id = 0
        for menu in menus:
            categories = menu.get("menu_categories", [])
            for cat in categories:
                cat_name = cat.get("name", "")
                for product in cat.get("products", []):
                    item_id += 1
                    price = 0.0
                    product_id = product.get("id", 0)
                    variation_id = 0
                    variation_code = ""
                    pv = product.get("product_variations", [])
                    if pv:
                        price = pv[0].get("price", 0.0)
                        variation_id = pv[0].get("id", 0)
                        variation_code = pv[0].get("code", "")
                    if not price:
                        price = product.get("price", 0.0)
                    self.menu_items.append(MenuItem(
                        id=item_id,
                        name=product.get("name", ""),
                        price=float(price),
                        description=product.get("description", ""),
                        category=cat_name,
                        product_id=product_id,
                        variation_id=variation_id,
                        variation_code=variation_code,
                    ))


@dataclass
class CartItem:
    menu_item: MenuItem
    quantity: int
    restaurant_name: str

    @property
    def subtotal(self) -> float:
        return self.menu_item.price * self.quantity


@dataclass
class Cart:
    items: list[CartItem] = field(default_factory=list)
    restaurant: Restaurant | None = None

    @property
    def total(self) -> float:
        return sum(item.subtotal for item in self.items)

    @property
    def total_with_delivery(self) -> float:
        fee = self.restaurant.delivery_fee if self.restaurant else 0
        return self.total + fee

    def add(self, menu_item: MenuItem, quantity: int, restaurant: Restaurant):
        if self.restaurant and self.restaurant.code != restaurant.code:
            raise ValueError("DIFF_RESTAURANT")
        self.restaurant = restaurant
        for item in self.items:
            if item.menu_item.id == menu_item.id:
                item.quantity += quantity
                return
        self.items.append(CartItem(menu_item, quantity, restaurant.name))

    def remove(self, index: int):
        if 0 <= index < len(self.items):
            self.items.pop(index)
            if not self.items:
                self.restaurant = None

    def update_quantity(self, index: int, quantity: int):
        if 0 <= index < len(self.items):
            if quantity <= 0:
                self.remove(index)
            else:
                self.items[index].quantity = quantity

    def clear(self):
        self.items.clear()
        self.restaurant = None

    def to_summary(self) -> str:
        lines = []
        for item in self.items:
            lines.append(f"  {item.menu_item.name} x{item.quantity}  ${item.subtotal:.2f}")
        return "\n".join(lines)
