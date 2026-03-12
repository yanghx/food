import time
import uuid

import httpx

DISCO_BASE = "https://disco.deliveryhero.io"
FD_API_BASE = "https://sg.fd-api.com"
ONEMAP_BASE = "https://www.onemap.gov.sg/api/common/elastic/search"
MAX_RETRIES = 3

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.foodpanda.sg/",
    "Origin": "https://www.foodpanda.sg",
}


class FoodpandaAPI:
    def __init__(self, token: str = ""):
        self.token = token
        self.client = httpx.Client(timeout=30, follow_redirects=True)
        self.perseus_client_id = str(uuid.uuid4())
        self.perseus_session_id = str(uuid.uuid4())

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with automatic retry on 403 (PerimeterX)."""
        for attempt in range(MAX_RETRIES):
            resp = self.client.request(method, url, **kwargs)
            if resp.status_code != 403 or attempt == MAX_RETRIES - 1:
                return resp
            time.sleep(2 * (attempt + 1))
            # Rotate session IDs on retry
            self.perseus_session_id = str(uuid.uuid4())
        return resp

    def _disco_headers(self) -> dict:
        return {
            **COMMON_HEADERS,
            "x-disco-client-id": "web",
        }

    def _fd_headers(self) -> dict:
        headers = {
            **COMMON_HEADERS,
            "x-fp-api-key": "volo",
            "x-pd-language-id": "1",
            "x-country-code": "sg",
            "perseus-client-id": self.perseus_client_id,
            "perseus-session-id": self.perseus_session_id,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def resolve_postal_code(self, postal_code: str) -> dict | None:
        """Resolve a Singapore postal code using OneMap API."""
        try:
            resp = self.client.get(
                ONEMAP_BASE,
                params={
                    "searchVal": postal_code,
                    "returnGeom": "Y",
                    "getAddrDetails": "Y",
                },
                headers={"User-Agent": COMMON_HEADERS["User-Agent"]},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                r = results[0]
                return {
                    "latitude": float(r.get("LATITUDE", 0)),
                    "longitude": float(r.get("LONGITUDE", 0)),
                    "address": r.get("ADDRESS", ""),
                    "building": r.get("BUILDING", ""),
                    "postal": r.get("POSTAL", postal_code),
                }
            return None
        except Exception as e:
            raise APIError(f"地址解析失败: {e}")

    def list_restaurants(
        self,
        latitude: float,
        longitude: float,
        offset: int = 0,
        limit: int = 20,
        sort: str = "",
        cuisine: str = "",
    ) -> dict:
        """List nearby restaurants using the vendors-gateway API."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "language_id": 1,
            "include": "characteristics",
            "configuration": "Original",
            "country": "sg",
            "vertical": "restaurants",
            "opening_type": "delivery",
            "limit": limit,
            "offset": offset,
            "customer_type": "regular",
            "dynamic_pricing": 0,
            "use_free_delivery_label": "true",
            "tag_label_metadata": "true",
            "budgets": "",
            "cuisine": cuisine,
            "sort": sort,
        }
        try:
            resp = self._request("GET",
                f"{FD_API_BASE}/vendors-gateway/api/v1/pandora/vendors",
                params=params,
                headers=self._disco_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise APIError(f"获取餐厅列表失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise APIError(f"获取餐厅列表失败: {e}")

    def get_vendor(self, vendor_code: str, latitude: float, longitude: float) -> dict:
        """Get vendor details including menu (no auth required)."""
        params = {
            "include": "menus",
            "language_id": 1,
            "dynamic_pricing": 0,
            "opening_type": "delivery",
            "latitude": latitude,
            "longitude": longitude,
        }
        try:
            # Don't send bearer token — expired token causes 401 on this public endpoint
            headers = self._fd_headers()
            headers.pop("Authorization", None)
            resp = self._request("GET",
                f"{FD_API_BASE}/api/v5/vendors/{vendor_code}",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise APIError(f"获取餐厅详情失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise APIError(f"获取餐厅详情失败: {e}")

    def get_order_history(self) -> dict:
        """Get order history (requires authentication)."""
        if not self.token:
            raise APIError("需要登录 token 才能查看订单历史")
        try:
            resp = self._request("GET",
                f"{FD_API_BASE}/api/v5/orders/order_history",
                params={"include": "order_products,order_details", "limit": 20},
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"获取订单历史失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise APIError(f"获取订单历史失败: {e}")

    def search_restaurants(
        self, query: str, latitude: float, longitude: float, limit: int = 15
    ) -> list[dict]:
        """Search restaurants by fetching nearby vendors and filtering by name.

        The listing API does not support server-side text search, so we fetch
        a large batch and do client-side name matching.
        """
        data = self.list_restaurants(latitude, longitude, limit=200)
        items = data.get("data", {}).get("items", [])
        q = query.lower()
        # Exact substring matches first, then partial word matches
        exact = [it for it in items if q in it.get("name", "").lower()]
        if exact:
            return exact[:limit]
        # Try matching individual words
        words = q.split()
        partial = [it for it in items if any(w in it.get("name", "").lower() for w in words)]
        return partial[:limit]

    def get_saved_addresses(self) -> list[dict]:
        """Get saved delivery addresses from account (requires authentication)."""
        if not self.token:
            raise APIError("需要登录 Token 才能获取保存的地址")
        try:
            resp = self._request("GET",
                f"{FD_API_BASE}/api/v5/customers/addresses",
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data) if isinstance(data, dict) else data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"获取保存地址失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise APIError(f"获取保存地址失败: {e}")

    def cart_calculate(
        self,
        vendor_code: str,
        products: list[dict],
        latitude: float,
        longitude: float,
        vendor_latitude: float = 0,
        vendor_longitude: float = 0,
        address_id: str = "",
        postcode: str = "",
        voucher: str = "",
        delivery_instructions: str = "",
        order_time: str = "now",
    ) -> dict:
        """Calculate cart totals, delivery fees, and validate items.

        Real endpoint discovered via CDP: POST /api/v5/cart/calculate?include=expedition

        latitude/longitude: user's delivery location
        vendor_latitude/vendor_longitude: restaurant's location (affects delivery fee)
        order_time: "now" for immediate, or ISO 8601 like "2026-03-12T13:00:00+08:00"
        """
        if not self.token:
            raise APIError("需要登录 Token 才能结算")
        v_lat = vendor_latitude or latitude
        v_lng = vendor_longitude or longitude
        body = {
            "auto_apply_voucher": bool(voucher),
            "supported_features": {
                "support_voucher_soft_fail": True,
                "support_banned_products_soft_fail": True,
                "small_order_fee_enabled": True,
                "pd-qc-weight-stepper": True,
                "pd-tx-cash-to-online-payment-surcharge": False,
                "product_sampling": False,
                "sustainability_fees_enabled": True,
            },
            "payment": {
                "loyalty": {"balance": None, "points": 0, "selected_promotion_id": ""},
                "methods": [],
                "allowance_amount": 0,
            },
            "group_order": None,
            "joker": {"single_discount": True},
            "voucher_context": None,
            "joker_offer_id": "",
            "source": "",
            "voucher": voucher,
            "order_time": order_time,
            "expedition": {
                "delivery_option": "standard",
                "delivery_address": {
                    "id": address_id,
                    "postcode": postcode,
                    "delivery_instructions": delivery_instructions,
                },
                "type": "delivery",
                "latitude": latitude,
                "longitude": longitude,
            },
            "products": products,
            "vendor": {
                "code": vendor_code,
                "latitude": v_lat,
                "longitude": v_lng,
                "marketplace": False,
                "vertical": "restaurants",
            },
        }
        try:
            resp = self._request("POST",
                f"{FD_API_BASE}/api/v5/cart/calculate",
                params={"include": "expedition"},
                json=body,
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"购物车计算失败 (HTTP {e.response.status_code}): {e.response.text[:300]}")
        except Exception as e:
            raise APIError(f"购物车计算失败: {e}")

    def create_purchase_intent(
        self,
        vendor_code: str,
        subtotal: float,
        amount: float,
    ) -> dict:
        """Create a purchase intent (payment session).

        Real endpoint: POST /api/v5/purchase/intent?include=cashback&locale=zh_SG
        """
        if not self.token:
            raise APIError("需要登录 Token 才能下单")
        body = {
            "subtotal": subtotal,
            "currency": "SGD",
            "vendorCode": vendor_code,
            "amount": amount,
            "emoneyAmountToUse": 0,
            "expeditionType": "delivery",
            "paymentLimits": [
                {"limitCode": "foodafterdiscount", "limitAmount": subtotal},
                {"limitCode": "orderamountwithoutpaymentfee", "limitAmount": amount},
            ],
        }
        try:
            resp = self._request("POST",
                f"{FD_API_BASE}/api/v5/purchase/intent",
                params={"include": "cashback", "locale": "en_SG"},
                json=body,
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"创建支付意向失败 (HTTP {e.response.status_code}): {e.response.text[:300]}")
        except Exception as e:
            raise APIError(f"创建支付意向失败: {e}")

    def confirm_purchase_intent(
        self,
        intent_id: str,
        vendor_code: str,
        subtotal: float,
        amount: float,
        payment_method: str = "balance",
    ) -> dict:
        """Confirm purchase intent with payment method.

        Real endpoint: PUT /api/v5/purchase/intent/{id}?include=cashback&locale=zh_SG&fast-top-up=true

        payment_method: "balance" (pandapay/wallet), or card payment session id
        """
        if not self.token:
            raise APIError("需要登录 Token 才能下单")
        body = {
            "subtotal": subtotal,
            "currency": "SGD",
            "vendorCode": vendor_code,
            "amount": amount,
            "emoneyAmountToUse": amount if payment_method == "balance" else 0,
            "expeditionType": "delivery",
            "paymentLimits": [
                {"limitCode": "foodafterdiscount", "limitAmount": subtotal},
                {"limitCode": "orderamountwithoutpaymentfee", "limitAmount": amount},
            ],
            "paymentSessionDetails": {
                "selectedPaymentMethod": payment_method,
            },
        }
        if payment_method == "balance":
            body["wallet"] = {"topUp": {"fastTopUp": True}}
        try:
            resp = self._request("PUT",
                f"{FD_API_BASE}/api/v5/purchase/intent/{intent_id}",
                params={"include": "cashback", "locale": "en_SG", "fast-top-up": "true"},
                json=body,
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"确认支付失败 (HTTP {e.response.status_code}): {e.response.text[:300]}")
        except Exception as e:
            raise APIError(f"确认支付失败: {e}")

    def cart_checkout(
        self,
        vendor_code: str,
        products: list[dict],
        purchase_intent_id: str,
        expected_total: float,
        customer_id: str,
        customer_email: str,
        address: dict,
        latitude: float,
        longitude: float,
        payment_method: str = "balance",
        delivery_instructions: str = "",
        voucher: str = "",
        order_time: str = "now",
    ) -> dict:
        """Submit the order.

        Real endpoint: POST /api/v5/cart/checkout
        This is the final step after cart/calculate + purchase/intent.
        """
        if not self.token:
            raise APIError("需要登录 Token 才能下单")
        body = {
            "platform": "b2c",
            "expected_total_amount": expected_total,
            "customer": {
                "id": customer_id,
                "email": customer_email,
                "address_id": str(address.get("id", "")),
                "age_verification_token": "",
            },
            "expedition": {
                "delivery_address": {
                    "id": str(address.get("id", "")),
                    "address_line1": address.get("address_line1", ""),
                    "address_line2": str(address.get("address_line2", "")),
                    "latitude": address.get("latitude", latitude),
                    "longitude": address.get("longitude", longitude),
                    "postcode": str(address.get("postcode", "")),
                    "city_id": address.get("city_id", 1),
                    "building": address.get("building", ""),
                    "floor": address.get("floor", ""),
                    "delivery_instructions": delivery_instructions or address.get("delivery_instructions", ""),
                    "label": address.get("label") or "",
                    "company": address.get("company") or "",
                },
                "type": "delivery",
                "latitude": latitude,
                "longitude": longitude,
                "instructions": delivery_instructions,
                "delivery_instructions_tags": [],
                "delivery_option": "standard",
            },
            "order_time": order_time,
            "source": "volo",
            "vendor": {
                "code": vendor_code,
                "latitude": latitude,
                "longitude": longitude,
                "marketplace": False,
                "vertical": "restaurants",
            },
            "products": products,
            "payment": {
                "client_redirect_url": "https://www.foodpanda.sg/payments/handle-payment/",
                "purchase_intent_id": purchase_intent_id,
                "currency": "SGD",
                "methods": [{"amount": expected_total, "metadata": {}, "method": payment_method}],
            },
            "voucher": voucher,
            "voucher_context": {"construct_id": ""},
            "bypass_duplicate_order_check": False,
            "supported_features": {
                "support_banned_products_soft_fail": True,
                "small_order_fee_enabled": True,
                "pd-tx-cash-to-online-payment-surcharge": False,
            },
            "joker_offer_id": "",
            "joker": {"single_discount": True},
        }
        try:
            resp = self._request("POST",
                f"{FD_API_BASE}/api/v5/cart/checkout",
                json=body,
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"下单失败 (HTTP {e.response.status_code}): {e.response.text[:300]}")
        except Exception as e:
            raise APIError(f"下单失败: {e}")

    def get_customer_info(self) -> dict:
        """Get customer profile (id, email, etc)."""
        if not self.token:
            raise APIError("需要登录 Token")
        try:
            resp = self._request("GET",
                f"{FD_API_BASE}/api/v5/customers",
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise APIError("Token 已过期，请重新设置")
            raise APIError(f"获取客户信息失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise APIError(f"获取客户信息失败: {e}")

    def get_payment_status(self, purchase_id: str, order_code: str) -> dict:
        """Poll payment status after checkout."""
        try:
            resp = self._request("GET",
                f"{FD_API_BASE}/api/v5/payment/status",
                params={"purchaseId": purchase_id, "platformReferenceId": order_code},
                headers=self._fd_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    def close(self):
        self.client.close()


class APIError(Exception):
    pass
