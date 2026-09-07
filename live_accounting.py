"""Keep strategy capital independent from the exchange execution account."""
import math

EXECUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_accounting (
    order_id INTEGER PRIMARY KEY,
    ledger_mode TEXT NOT NULL,
    execution_entry_price REAL,
    execution_base_quantity REAL,
    execution_close_price REAL,
    close_client_order_id TEXT,
    close_price_source TEXT,
    FOREIGN KEY(order_id) REFERENCES orders(id)
)
"""


def reconcile_entry(updates):
    price = float(updates["entry_price"])
    quantity = float(updates["position_size"])
    leverage = float(updates["leverage"])
    if not all(math.isfinite(x) and x > 0 for x in (price, quantity, leverage)):
        raise ValueError("Executed price, base quantity and leverage must be positive and finite")
    notional = price * quantity
    margin = notional / leverage
    updates["balance"] += updates["margin"] - margin
    updates["margin"] = margin
    updates["position_value"] = notional
    return updates


def apply_execution_to_ledger(updates, base_quantity, fill_price, sync_balance):
    # With SYNC=False, entry price, size, margin AND balance belong to the
    # local strategy. A differently funded exchange account cannot overwrite them.
    if sync_balance:
        if base_quantity is not None:
            updates["position_size"] = base_quantity
        if fill_price is not None:
            updates["entry_price"] = fill_price
        reconcile_entry(updates)
    return updates


def resolve_close_fill(client, response):
    client_id = response.get("client_order_id") if isinstance(response, dict) else None
    try:
        price = client.resolve_average_fill_price(response=response, client_order_id=client_id)
        if price is not None and math.isfinite(float(price)) and float(price) > 0:
            return float(price)
    except Exception:
        pass
    return None


def resolve_close_price(client, response, candle_price, logger):
    price = resolve_close_fill(client, response)
    if price is not None:
        return price
    logger.warning("Close fill price unavailable: exchange PnL is ESTIMATED from candle price; reconcile with exchange fills and fees.")
    return candle_price
