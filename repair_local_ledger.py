"""Rebuild the local strategy ledger from recorded candles and recorded allocations.
Does not resimulate historical trading decisions or modify exchange order quantities.
Run with a stopped bot: python repair_local_ledger.py database.db [--apply]
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math
import sqlite3
from live_accounting import EXECUTION_SCHEMA
from trademanager import calculate_trade_metrics

REPAIR_KEY = "local-ledger-separation-v2"


def snapshot(conn):
    return {
        "orders": [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")],
        "runtime": [dict(r) for r in conn.execute("SELECT * FROM runtime_state ORDER BY mode")],
        "capital": [dict(r) for r in conn.execute("SELECT * FROM balance_state ORDER BY mode")],
        "candles": [tuple(r) for r in conn.execute("SELECT symbol,close_times,close_prices FROM symbol_data ORDER BY id")],
    }


def build_plan(data):
    orders = data["orders"]
    state = next((r for r in data["capital"] if r["mode"] == "local"), None)
    if not state or not orders:
        raise ValueError("A recorded local capital baseline and orders are required")
    candles = {}
    for symbol, timestamp, price in data["candles"]:
        key = (symbol, timestamp)
        value = float(price)
        if key in candles and not math.isclose(candles[key],value,rel_tol=1e-12):
            raise ValueError("Conflicting candle prices: " + str(key))
        candles[key] = value
    balance = float(state["first_balance"])
    balance_no_fee = float(orders[0]["balance_before_trade_no_fee"] or balance)
    previous_save = 0.0
    monthly = {}
    plan = []
    seen_open = False
    for row in orders:
        if seen_open or row["status"] not in ("open","closed"):
            raise ValueError("Only sequential completed trades and one final open trade are supported")
        seen_open = row["status"] == "open"
        entry = candles.get((row["symbol"],row["open_time"]))
        if entry is None:
            raise ValueError(f"Missing entry candle for order {row['id']}")
        margin = float(row["margin"])
        # Undo the prior narrowly scoped repair that incorrectly reclassified
        # the audited local allocation as exchange margin.
        if row["id"] == 16 and row["client_order_id"] == "BOT_MA_000032" and math.isclose(margin,273.742183,rel_tol=1e-10):
            margin = 515.0
        no_fee_margin = float(row["margin_no_fee"])
        leverage = float(row["leverage"])
        if not all(math.isfinite(x) and x>0 for x in (entry,margin,no_fee_margin,leverage)):
            raise ValueError("Invalid allocation or entry price")
        if margin > balance + 1e-8:
            raise ValueError(f"Recorded allocation exceeds rebuilt cash at order {row['id']}; manual review required")
        size = margin*leverage/entry
        size_no_fee = no_fee_margin*leverage/entry
        save = float(row["save_money"] or 0)
        # Recorded transfers are historical events; do not invent new trades or
        # recalculate past leverage/monthly withdrawals using today's settings.
        transfer = save-previous_save
        before = balance
        before_no_fee = balance_no_fee
        rate = float(row["fee_rate"])
        values = dict(entry_price=entry,margin=margin,position_size=size,
                      position_size_no_fee=size_no_fee,position_value=margin*leverage,
                      position_value_no_fee=no_fee_margin*leverage,
                      balance_before_trade=before,balance_before_trade_no_fee=before_no_fee,
                      entry_fee=entry*size*rate)
        if seen_open:
            balance = before-margin-transfer
            balance_no_fee = before_no_fee-no_fee_margin
        else:
            close = candles.get((row["symbol"],row["close_time"]))
            if close is None:
                raise ValueError(f"Missing close candle for order {row['id']}")
            metrics = calculate_trade_metrics(row["side"],entry,close,size,margin,rate,before)
            pnl_no_fee=size_no_fee*(close-entry)*(-1 if row["side"]=="short" else 1)
            balance = before+metrics["profit"]-transfer
            balance_no_fee = before_no_fee+pnl_no_fee
            month=row["close_time"][:7]
            monthly[month]=monthly.get(month,0)+metrics["profit_percent"]
            values.update(metrics,close_price=close,pnl_no_fee=pnl_no_fee,
                          balance_after_trade=before+metrics["profit"],
                          price_change_percent=(close-entry)/entry*100*(-1 if row["side"]=="short" else 1))
        values.update(balance=balance,balance_without_fee=balance_no_fee,
                      total_assets=balance+save+(margin if seen_open else 0))
        changes={k:{"old":row[k],"new":v} for k,v in values.items()
                 if row[k] is None or not math.isclose(float(row[k]),v,rel_tol=1e-11,abs_tol=1e-9)}
        plan.append(dict(id=row["id"],values=values,changes=changes,
                         execution_entry_price=row["entry_price"] if row["entry_price"] != entry else None,
                         execution_base_quantity=row["position_size"] if row["id"]>=14 and row["bot_quantity"] else None))
        previous_save=save
    runtime=next((r for r in data["runtime"] if r["mode"]=="local"),None)
    current_month=(runtime["updated_at"][:7] if runtime else orders[-1]["open_time"][:7])
    return dict(orders=plan,monthly=monthly,current_month=current_month,
                current_month_profit=monthly.get(current_month,0),
                balance=balance,total_assets=plan[-1]["values"]["total_assets"],
                previous_balance=orders[-1]["balance"],previous_total_assets=orders[-1]["total_assets"])


def repair(path, apply=False):
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+"?mode="+("rw" if apply else "ro"),uri=True)) as conn:
        conn.row_factory=sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='ledger_repairs'").fetchone():
            if conn.execute("SELECT 1 FROM ledger_repairs WHERE repair_key=?",(REPAIR_KEY,)).fetchone():
                return {"already_applied":True}
        data=snapshot(conn)
        plan=build_plan(data)
        if not apply:
            return plan
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup=path.with_name(path.name+".before-local-ledger-"+stamp)
        with closing(sqlite3.connect(backup)) as target:
            conn.backup(target)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if snapshot(conn)!=data:
                raise RuntimeError("Database changed during audit; stop bot and retry")
            conn.execute(EXECUTION_SCHEMA)
            conn.execute("CREATE TABLE IF NOT EXISTS ledger_repairs (repair_key TEXT PRIMARY KEY, applied_at TEXT, audit_json TEXT)")
            for item in plan["orders"]:
                values=item["values"]
                assignments=", ".join(f'"{k}"=?' for k in values)
                conn.execute(f"UPDATE orders SET {assignments} WHERE id=?",[*values.values(),item["id"]])
                conn.execute(
                    "INSERT INTO order_accounting (order_id,ledger_mode,execution_entry_price,execution_base_quantity) VALUES (?,'local',?,?) "
                    "ON CONFLICT(order_id) DO UPDATE SET ledger_mode='local', execution_entry_price=COALESCE(order_accounting.execution_entry_price,excluded.execution_entry_price),execution_base_quantity=COALESCE(order_accounting.execution_base_quantity,excluded.execution_base_quantity)",
                    (item["id"],item["execution_entry_price"],item["execution_base_quantity"]),
                )
            conn.execute("UPDATE runtime_state SET profit_percent_per_month=? WHERE mode='local'",(plan["current_month_profit"],))
            conn.execute("INSERT INTO ledger_repairs VALUES (?,?,?)",(REPAIR_KEY,stamp,json.dumps({"backup":str(backup),"before":data["orders"],"plan":plan})))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return dict(applied=True,backup=str(backup),plan=plan)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--report",help="Write full JSON audit to this file")
    args=parser.parse_args()
    result=repair(args.database,args.apply)
    if args.report:
        Path(args.report).write_text(json.dumps(result,indent=2),encoding="utf-8")
    plan=result.get("plan",result)
    print(json.dumps({k:v for k,v in plan.items() if k!="orders"},indent=2))
    for item in plan.get("orders",[]):
        if item["changes"]:
            print(json.dumps({"id":item["id"],"changes":item["changes"]}))
