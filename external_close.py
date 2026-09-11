"""Settle a confirmed external close using an explicitly estimated candle price."""
import math
from datetime import datetime


def settle_external_close(conn, order_id, close_time, close_price):
    price = float(close_price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("A valid last candle price is required for external settlement")
    # A guarded transaction makes repeated observations safe, including another
    # worker having already reconciled this order.
    with conn:
        cur = conn.execute("SELECT * FROM orders WHERE id=? AND status='open'", (order_id,))
        row = cur.fetchone()
        if row is None:
            return False
        order = dict(zip([item[0] for item in cur.description], row))
        entry = float(order['entry_price'])
        qty = float(order['position_size'])
        direction = 1 if order['side'].lower() == 'long' else -1
        fee_rate = float(order['fee_rate'] if order['fee_rate'] is not None else .0005)
        pnl = direction * qty * (price - entry)
        entry_fee, exit_fee = entry * qty * fee_rate, price * qty * fee_rate
        profit = pnl - entry_fee - exit_fee
        before = order['balance_before_trade']
        if before is None:
            before = float(order['balance']) + float(order['margin'])
        before_no_fee = order['balance_before_trade_no_fee']
        if before_no_fee is None:
            before_no_fee = float(order['balance_without_fee']) + float(order['margin_no_fee'])
        qty_no_fee = order['position_size_no_fee']
        pnl_no_fee = direction * float(qty_no_fee if qty_no_fee is not None else qty) * (price - entry)
        balance = float(before) + profit
        duration = max(0, int((datetime.fromisoformat(str(close_time).replace('Z', '+00:00')) -
                               datetime.fromisoformat(order['open_time'].replace('Z', '+00:00'))).total_seconds()))
        values = dict(status='closed', current_position=None, close_price=price,
                      close_time=str(close_time), duration_seconds=duration,
                      profit=profit, profit_percent=profit * 100 / before if before else 0,
                      pnl=pnl, pnl_percent=pnl * 100 / order['margin'] if order['margin'] else 0,
                      pnl_no_fee=pnl_no_fee, entry_fee=entry_fee, exit_fee=exit_fee,
                      total_fee=entry_fee + exit_fee, fee_rate=fee_rate,
                      balance=balance, balance_after_trade=balance,
                      balance_without_fee=float(before_no_fee) + pnl_no_fee,
                      total_assets=balance + float(order['save_money'] or 0),
                      price_change_percent=direction * (price - entry) * 100 / entry)
        changed = conn.execute('UPDATE orders SET ' + ','.join(k + '=?' for k in values) +
                               " WHERE id=? AND status='open'", (*values.values(), order_id)).rowcount
        if changed and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_accounting'").fetchone():
            conn.execute("UPDATE order_accounting SET close_client_order_id='EXTERNAL_CLOSE', "
                         "close_price_source='last_candle_estimate' WHERE order_id=?", (order_id,))
        return bool(changed)
