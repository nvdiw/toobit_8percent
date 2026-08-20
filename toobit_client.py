import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import requests

# My Codes
from database import Database


class ToobitClient:
    def __init__(
        self,
        base_url="https://api.toobit.com",
        category="USDT",
        balance_asset="USDT",
        recv_window=5000,
        timeout=10,
        max_retries=3,
        backoff_base_seconds=1.0,
        max_backoff_seconds=8.0,
    ):
        self.base_url = base_url
        self.category = category
        self.balance_asset = balance_asset
        self.recv_window = recv_window
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.db = Database()

    def _retry_delay(self, attempt_index):
        delay = self.backoff_base_seconds * (2 ** max(0, attempt_index - 1))
        return min(delay, self.max_backoff_seconds)

    #count orderID 
    def generate_client_order_id(self, strategy):
        strategy = strategy.upper()

        counter = self.db.increment_order_counter(strategy)

        return f"BOT_{strategy}_{counter:06d}"

    @staticmethod
    def _is_retryable_status(status_code):
        return status_code in (408, 429, 500, 502, 503, 504)

    def _load_keys(self):
        api_key = os.getenv("TOOBIT_API_KEY")
        api_secret = os.getenv("TOOBIT_API_SECRET")

        if api_key and api_secret:
            return api_key.strip(), api_secret.strip()

        raise RuntimeError(
            "Toobit API keys not found in environment. "
            "Set TOOBIT_API_KEY and TOOBIT_API_SECRET (for example via .env)."
        )

    @staticmethod
    def _format_number(value, precision=8):
        if value is None:
            return None
        try:
            value = float(value)
        except Exception:
            return str(value)
        formatted = f"{value:.{precision}f}".rstrip("0").rstrip(".")
        return formatted if formatted else "0"

    def _signed_request(self, method, path, params=None):
        api_key, api_secret = self._load_keys()

        params = params or {}
        params = {k: v for k, v in params.items() if v is not None}
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.recv_window

        query = urlencode([(k, str(params[k])) for k in params])
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        url = f"{self.base_url}{path}?{query}&signature={signature}"
        headers = {"X-BB-APIKEY": api_key}

        total_attempts = self.max_retries + 1
        last_error = None

        for attempt in range(1, total_attempts + 1):
            try:
                response = requests.request(method, url, headers=headers, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < total_attempts:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise RuntimeError(
                    f"Toobit request failed after {total_attempts} attempts: {exc}"
                ) from exc

            try:
                data = response.json()
            except Exception:
                text = response.text
                if self._is_retryable_status(response.status_code) and attempt < total_attempts:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise RuntimeError(f"Toobit non-JSON response: HTTP {response.status_code} -> {text}")

            if response.status_code != 200:
                if self._is_retryable_status(response.status_code) and attempt < total_attempts:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise RuntimeError(f"Toobit HTTP {response.status_code}: {data}")

            if isinstance(data, dict) and data.get("code") not in (None, 200):
                raise RuntimeError(f"Toobit error {data.get('code')}: {data.get('msg')}")

            return data

        if last_error is not None:
            raise RuntimeError(
                f"Toobit request failed after {total_attempts} attempts: {last_error}"
            ) from last_error
        raise RuntimeError("Toobit request failed without a response.")

    def get_balance(self, asset=None):
        asset = asset or self.balance_asset
        data = self._signed_request(
            "GET",
            "/api/v1/futures/balance",
            params={"category": self.category},
        )

        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected Toobit balance response: {data}")

        for item in data:
            if item.get("asset") == asset:
                available = item.get("availableBalance")
                total = item.get("balance")
                return float(available if available is not None else total)

        raise RuntimeError(f"Asset {asset} not found in Toobit balance response.")

    def get_positions(self, symbol=None, side=None):
        params = {"category": self.category}
        if symbol:
            params["symbol"] = symbol
        if side:
            params["side"] = side

        data = self._signed_request("GET", "/api/v1/futures/positions", params=params)

        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected Toobit positions response: {data}")

        return data

    def get_open_position(self, symbol, side=None):
        positions = self.get_positions(symbol=symbol, side=side)
        expected_side = str(side).upper() if side else None
        for pos in positions:
            try:
                qty = float(pos.get("position", 0))
            except Exception:
                qty = 0
            position_side = str(pos.get("side") or "").upper()
            if (
                pos.get("symbol") == symbol
                and qty > 0
                and (expected_side is None or position_side == expected_side)
            ):
                return pos
        return None

    def set_leverage(self, symbol, leverage):
        return self._signed_request(
            "POST",
            "/api/v1/futures/leverage",
            params={
                "symbol": symbol,
                "leverage": int(leverage),
                "category": self.category,
            },
        )

    def place_order(self, symbol, side, quantity=None, value_quantity=None, price_type="MARKET", order_type="LIMIT", strategy=None, client_order_id=None,):
        if quantity is None and value_quantity is None:
            raise RuntimeError("Toobit order requires quantity or value_quantity.")

        if order_type:
            order_type = str(order_type).upper()
        if price_type:
            price_type = str(price_type).upper()

        if order_type == "MARKET":
            order_type = "LIMIT"
            if not price_type:
                price_type = "MARKET"

        if client_order_id is None and strategy is not None:
            client_order_id = self.generate_client_order_id(strategy)

        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "priceType": price_type,
            "category": self.category,
        }

        if client_order_id:
            params["newClientOrderId"] = client_order_id

        if quantity is not None:
            qty_val = float(quantity)
            if qty_val <= 0:
                raise RuntimeError("Toobit order quantity must be > 0.")
            params["quantity"] = self._format_number(qty_val, precision=6)

        if value_quantity is not None:
            val_qty = float(value_quantity)
            if val_qty <= 0:
                raise RuntimeError("Toobit order value_quantity must be > 0.")
            params["valueQuantity"] = self._format_number(val_qty, precision=2)

        response = self._signed_request(
            "POST",
            "/api/v1/futures/order",
            params=params,
        )

        response["client_order_id"] = client_order_id

        return response

    def get_order(self, order_id=None, client_order_id=None):
        if order_id is None and not client_order_id:
            raise RuntimeError("Toobit order query requires order_id or client_order_id.")

        return self._signed_request(
            "GET",
            "/api/v1/futures/order",
            params={
                "orderId": order_id,
                "origClientOrderId": client_order_id,
                "type": "LIMIT",
                "category": self.category,
            },
        )

    def get_contract_multiplier(self, symbol):
        """Return the base-asset amount represented by one futures contract."""
        response = requests.get(
            f"{self.base_url}/api/v1/exchangeInfo",
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        for contract in payload.get("contracts", []):
            if contract.get("symbol") == symbol:
                multiplier = float(contract.get("contractMultiplier", 0))
                if multiplier > 0:
                    return multiplier
        raise RuntimeError(f"Contract multiplier not found for {symbol}.")

    def contracts_to_base_quantity(self, symbol, contract_quantity):
        quantity = float(contract_quantity)
        if quantity <= 0:
            raise RuntimeError("Executed contract quantity must be > 0.")
        return quantity * self.get_contract_multiplier(symbol)

    def resolve_average_fill_price(self, response=None, client_order_id=None):
        """Resolve the positive average fill price from an order response/query."""
        details = self.order_details(response)
        try:
            price = float(details.get("avgPrice", 0))
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            return price
        if client_order_id:
            try:
                queried = self.get_order(client_order_id=client_order_id)
            except Exception:
                return None
            details = self.order_details(queried)
            try:
                price = float(details.get("avgPrice", 0))
            except (TypeError, ValueError):
                price = 0.0
        return price if price > 0 else None

    @staticmethod
    def order_details(response):
        if not isinstance(response, dict):
            return {}
        data = response.get("data")
        if isinstance(data, dict):
            return data
        order = response.get("order")
        if isinstance(order, dict):
            return order
        return response

    @classmethod
    def executed_quantity(cls, response):
        details = cls.order_details(response)
        for key in ("executedQty", "executeQty"):
            try:
                quantity = float(details.get(key, 0))
            except (TypeError, ValueError):
                continue
            if quantity > 0:
                return quantity
        return None

    @classmethod
    def exchange_order_id(cls, response):
        value = cls.order_details(response).get("orderId")
        return str(value) if value not in (None, "") else None

    def resolve_executed_quantity(self, response=None, client_order_id=None, attempts=5, delay=0.2):
        quantity = self.executed_quantity(response)
        if quantity is not None:
            return quantity

        if not client_order_id:
            return None

        for attempt in range(attempts):
            queried = self.get_order(client_order_id=client_order_id)
            quantity = self.executed_quantity(queried)
            if quantity is not None:
                return quantity
            if attempt + 1 < attempts:
                time.sleep(delay)
        return None

    def close_position(self, symbol, side, strategy, quantity):
        side = side.upper()
        try:
            requested_qty = float(quantity)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Bot-owned Toobit quantity is missing or invalid; refusing to close.") from exc
        if requested_qty <= 0:
            raise RuntimeError("Bot-owned Toobit quantity must be > 0; refusing to close.")

        pos = self.get_open_position(symbol=symbol, side=side)
        if not pos:
            raise RuntimeError("No open Toobit position to close.")

        qty = pos.get("available")
        if qty is None:
            qty = pos.get("position")

        try:
            qty = float(qty)
        except Exception:
            qty = 0

        if qty <= 0:
            try:
                qty = float(pos.get("position", 0))
            except Exception:
                qty = 0

        if qty <= 0:
            raise RuntimeError("Toobit position quantity is zero.")

        # A Toobit position can aggregate manual and bot trades. If the total
        # available quantity has fallen below the bot-owned amount, ownership of
        # the remainder is ambiguous, so fail closed instead of touching it.
        if qty + 1e-12 < requested_qty:
            raise RuntimeError(
                "Available Toobit quantity is smaller than the bot-owned quantity; "
                "refusing to close an ambiguous position."
            )
        qty = requested_qty

        if side == "LONG":
            close_side = "SELL_CLOSE"
        elif side == "SHORT":
            close_side = "BUY_CLOSE"
        else:
            raise RuntimeError(f"Unknown position side: {side}")

        return self.place_order(
            symbol=symbol,
            side=close_side,
            quantity=qty,
            price_type="MARKET",
            order_type="LIMIT",
            strategy=strategy,
        )
