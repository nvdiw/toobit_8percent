import os

from toobit_client import ToobitClient

API_TRADE_CHOICES = ("future-trade", "copy-trade")


def add_api_trade_argument(parser):
    parser.add_argument(
        "--api-trade",
        choices=API_TRADE_CHOICES,
        default="future-trade",
        help="Select normal Futures or Lead Trader Copy Trading execution.",
    )


class FutureTradeExecutor(ToobitClient):
    api_trade = "future-trade"
    mode_label = "FUTURE-TRADE"


class CopyTradeExecutor(ToobitClient):
    api_trade = "copy-trade"
    mode_label = "COPY-TRADE"
    leader_positions_path = "/api/v2/copy-trading/leader/orders/current"

    def _load_keys(self):
        if self.api_key and self.api_secret:
            return self.api_key, self.api_secret
        api_key = os.getenv("TOOBIT_COPY_API_KEY")
        api_secret = os.getenv("TOOBIT_COPY_API_SECRET")
        if api_key and api_secret:
            return api_key.strip(), api_secret.strip()
        raise RuntimeError("copy-trade selected but TOOBIT_COPY_API_KEY / TOOBIT_COPY_API_SECRET are missing.")

    def get_positions(self, symbol=None, side=None):
        payload = self._signed_request("GET", self.leader_positions_path)
        positions = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(positions, list):
            raise RuntimeError(f"Unexpected Toobit lead positions response: {payload}")
        expected_side = str(side).upper() if side else None
        result = []
        for item in positions:
            mapped = dict(item)
            mapped["symbol"] = item.get("symbolId")
            mapped["side"] = "LONG" if int(item.get("isLong", 0)) == 1 else "SHORT"
            try:
                contract_quantity = float(item.get("quantity") or 0)
                if abs(contract_quantity - round(contract_quantity)) < 1e-9:
                    contract_quantity = int(round(contract_quantity))
            except (TypeError, ValueError):
                contract_quantity = 0
            mapped["copyQuantity"] = item.get("quantity")
            mapped["position"] = contract_quantity
            mapped["available"] = contract_quantity
            if symbol and mapped["symbol"] != symbol:
                continue
            if expected_side and mapped["side"] != expected_side:
                continue
            result.append(mapped)
        return result

    def validate_connection(self):
        self._load_keys()
        return self.get_positions()


def get_trade_executor(api_trade="future-trade", **kwargs):
    if api_trade not in API_TRADE_CHOICES:
        raise ValueError(f"Unsupported API trade mode: {api_trade}")
    cls = CopyTradeExecutor if api_trade == "copy-trade" else FutureTradeExecutor
    return cls(**kwargs)
