# Calculate Trade Duration
from datetime import datetime, timezone


def select_leverage(balance, tactical_balance, leverage, safe_low, safe_med, safe_high):
    """Select leverage from the account drawdown relative to tactical balance."""
    balance = float(balance)
    tactical_balance = float(tactical_balance)
    if tactical_balance <= 0:
        raise ValueError("tactical_balance must be greater than zero")

    balance_ratio = balance / tactical_balance
    if balance_ratio <= 0.80:
        return safe_low
    if balance_ratio <= 0.85:
        return safe_med
    if balance_ratio <= 0.90:
        return safe_high
    return leverage


def calculate_margin(balance, tactical_balance, trade_amount_percent):
    """Risk a fraction of tactical capital, capped by available balance."""
    balance = float(balance)
    tactical_balance = float(tactical_balance)
    trade_amount_percent = float(trade_amount_percent)
    if balance <= 0 or tactical_balance <= 0 or trade_amount_percent <= 0:
        return 0.0
    return min(balance, tactical_balance * trade_amount_percent)


def calculate_trade_metrics(
    side, entry_price, close_price, position_size, margin, fee_rate,
    balance_before_trade,
):
    """Return consistently based gross PnL and net profit metrics."""
    direction = -1.0 if str(side).strip().lower() in {"short", "sell"} else 1.0
    pnl = position_size * (close_price - entry_price) * direction
    entry_fee = entry_price * position_size * fee_rate
    exit_fee = close_price * position_size * fee_rate
    total_fee = entry_fee + exit_fee
    profit = pnl - total_fee
    pnl_percent = pnl * 100 / margin if margin else 0.0
    profit_percent = profit * 100 / balance_before_trade if balance_before_trade else 0.0
    return {
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "profit": profit,
        "profit_percent": profit_percent,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "total_fee": total_fee,
    }


def trade_duration(open_time: str, close_time: str):
    """Return elapsed whole days/hours/minutes for ISO-8601 timestamps."""

    def parse(value):
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid trade timestamp: {value!r}") from exc

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    diff = parse(close_time) - parse(open_time)
    total_minutes = int(diff.total_seconds() // 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)

    return days, hours, minutes


def accumulate_monthly_profit_percent(current_percent, trade_profit_percent):
    """Track strategy returns without mixing them with unallocated account cash."""
    return float(current_percent or 0) + float(trade_profit_percent or 0)


# Trade manager class to encapsulate open/close logic without changing behavior
class TradeManager:
    def __init__(
        self,
        csv_logger,
        first_balance,
        monthly_profit_percent_stop_trade,
        tactical_balance,
        monthly_close_filter,
        monthly_compound,
        leverage,
        safe_leverage_low,
        safe_leverage_med,
        safe_leverage_high,
        leverage_balance=None,
        leverage_tactical_balance=None,
    ):
        self.csv_logger = csv_logger
        self.first_balance = first_balance
        self.monthly_profit_percent_stop_trade = monthly_profit_percent_stop_trade
        self.tactical_balance = tactical_balance
        self.monthly_close_filter = monthly_close_filter
        self.monthly_compound = monthly_compound
        self.leverage = leverage
        self.safe_leverage_low = safe_leverage_low
        self.safe_leverage_med = safe_leverage_med
        self.safe_leverage_high = safe_leverage_high
        self.leverage_balance = leverage_balance
        self.leverage_tactical_balance = leverage_tactical_balance

    def _select_leverage(self, fallback_balance):
        risk_balance = (
            fallback_balance
            if self.leverage_balance is None
            else self.leverage_balance
        )
        risk_tactical = (
            self.tactical_balance
            if self.leverage_tactical_balance is None
            else self.leverage_tactical_balance
        )
        return select_leverage(
            risk_balance, risk_tactical, self.leverage,
            self.safe_leverage_low, self.safe_leverage_med, self.safe_leverage_high,
        )


    # open long processes
    def open_long(self, open_prices, open_times,
                    balance, balance_without_fee, first_balance,
                    trade_amount_percent, margin_balance, leverage):

        entry_price = open_prices

        balance_before_trade = balance
        balance_before_trade_no_fee = balance_without_fee

        # ---------- Margin ----------
        margin = calculate_margin(balance, self.tactical_balance, trade_amount_percent)
        
        # ---------- Leverage ----------
        leverage = self._select_leverage(balance)

        position_value = margin * leverage
        position_size = position_value / entry_price

        margin_no_fee = calculate_margin(
            balance_without_fee, self.tactical_balance, trade_amount_percent
        )
        position_value_no_fee = margin_no_fee * leverage
        position_size_no_fee = position_value_no_fee / entry_price

        # update balance after allocating margin
        balance -= margin
        balance_without_fee -= margin_no_fee

        # update open time and current position
        open_time_value = open_times
        current_position = "long"

        print("Open LONG at price:", entry_price, "$", "| Open Time:", open_time_value, "| leverage:", leverage)

        return {
            'entry_price': entry_price,
            'balance': balance,
            'balance_without_fee': balance_without_fee,
            'balance_before_trade': balance_before_trade,
            'balance_before_trade_no_fee': balance_before_trade_no_fee,
            'margin': margin,
            'leverage': leverage,
            'position_value': position_value,
            'position_size': position_size,
            'margin_no_fee': margin_no_fee,
            'position_value_no_fee': position_value_no_fee,
            'position_size_no_fee': position_size_no_fee,
            'open_time_value': open_time_value,
            'current_position': current_position
        }


    # close long processes
    def close_long(self, open_prices, open_times,
                entry_price, position_size, position_size_no_fee,
                fee_rate, margin, margin_no_fee,
                balance, balance_without_fee,
                balance_before_trade, balance_before_trade_no_fee,
                deducting_fee_total, profits_lst, total_profit_percent,
                count_closed_orders, equity_curve,
                max_drawdown, total_wins, total_wins_long, total_losses,
                total_long, cooldown_after_big_pnl, leverage,
                cooldown_until_index, open_time_value, csv_logger, trade_amount_percent, profit_percent_per_month,
                save_money, trade_power):

        close_price = open_prices

        # PnL
        metrics = calculate_trade_metrics(
            "long", entry_price, close_price, position_size, margin, fee_rate,
            balance_before_trade,
        )
        pnl = metrics["pnl"]
        pnl_no_fee = position_size_no_fee * (close_price - entry_price)

        # Fee like Toobit
        entry_fee = metrics["entry_fee"]
        exit_fee = metrics["exit_fee"]
        total_fee = metrics["total_fee"]

        # Update balance
        balance += margin + pnl - total_fee
        balance_without_fee += margin_no_fee + pnl_no_fee

        # profit after fee
        profit = metrics["profit"]
        profit_percent = metrics["profit_percent"]
        profit_percent_per_month = accumulate_monthly_profit_percent(
            profit_percent_per_month,
            profit_percent,
        )
        pnl_percent = metrics["pnl_percent"]
        balance_after_trade = balance
        position_value = entry_price * position_size
        position_value_no_fee = entry_price * position_size_no_fee
        price_change_percent = (close_price - entry_price) * 100 / entry_price

        deducting_fee_total += total_fee
        profits_lst.append(profit)
        total_profit_percent += profit_percent
        count_closed_orders += 1

        equity_curve.append(balance + save_money)
        # ---- calculate max drawdown ----
        peak = max(equity_curve)
        drawdown = (balance + save_money - peak) / peak * 100
        max_drawdown = min(max_drawdown, drawdown)

        # ---- count wins and losses ----
        if profit_percent > 0:
            total_wins += 1
            total_wins_long += 1
        else:
            total_losses += 1

        # ---- count LONG trades ----
        total_long += 1

        # ---- COOLDOWN AFTER BIG PROFIT ----
        pnl_percent_without_leverage = ((pnl / margin) * 100 ) / leverage
        if pnl_percent_without_leverage >= 4:
            cooldown_until_index = 0 + cooldown_after_big_pnl
            print(f"🟡 Cooldown Activated (LONG) until candle index {cooldown_until_index}")

        close_time_value = open_times
        days, hours, minutes = trade_duration(open_time_value, close_time_value)
        duration_seconds = days * 86400 + hours * 3600 + minutes * 60


        print("Close LONG at price:", close_price, "$", "| Close Time:", close_time_value, "| leverage:", leverage)
        print("Balance:", round(balance_before_trade, 2), "$", "→", round(balance, 2), "$", "| Save Money:", round(save_money, 2), "$")
        print("Balance (no fee):",
            round(balance_before_trade_no_fee, 2), "$", "→", round(balance_without_fee, 2), "$")
        print("pnl:", round(pnl, 2), "$ |", round(pnl_percent, 2), "% |" , "Amount:", round(margin), "$")
        print("fee:", round(total_fee, 2), "$")
        print("Profit:", round(profit, 2), "$ |", round(profit_percent, 2), "%")
        print(f"Trade Duration: {days} days, {hours} hours, {minutes} minutes")
        print("-" * 90)

        csv_logger.log_trade(
            "LONG",
            open_time_value,
            close_time_value,
            entry_price,
            close_price,
            round(balance_before_trade, 2),
            round(balance, 2),
            round(margin , 2),
            leverage,
            trade_amount_percent,
            round(profit, 2),
            round(profit_percent, 2),
            round(pnl_percent, 2),
            round(total_fee, 4),
            days,
            hours,
            minutes,
            save_money,
            profit_percent_per_month
        )

        # ---- save money ----
        if balance < self.tactical_balance * 75 / 100:
            if save_money >= self.tactical_balance * 25 / 100:
                balance += self.tactical_balance * 25 / 100
                save_money -= self.tactical_balance * 25 / 100

        # stop trade if we got monthly threshold for this month
        if self.monthly_close_filter == True :
            if profit_percent_per_month >= self.monthly_profit_percent_stop_trade:
                self.tactical_balance = self.tactical_balance + (self.tactical_balance * self.monthly_compound / 100)
                save_money += balance - self.tactical_balance
                balance = self.tactical_balance
                cooldown_until_index = 0
                trade_power = False    # off
        else:
            if balance >= self.tactical_balance * 1.08:
                self.tactical_balance = balance

        current_position = None

        return {
            'balance': balance,
            'balance_without_fee': balance_without_fee,
            'deducting_fee_total': deducting_fee_total,
            'profits_lst': profits_lst,
            'total_profit_percent': total_profit_percent,
            'count_closed_orders': count_closed_orders,
            'equity_curve': equity_curve,
            'max_drawdown': max_drawdown,
            'total_wins': total_wins,
            'total_wins_long': total_wins_long,
            'total_losses': total_losses,
            'total_long': total_long,
            'cooldown_until_index': cooldown_until_index,
            'current_position': current_position,
            'trade_power': trade_power,
            'profit_percent_per_month': profit_percent_per_month,
            'save_money' : save_money,
            'profit': profit,
            'profit_percent': profit_percent,
            'pnl': pnl,
            'pnl_percent': pnl_percent,
            'pnl_no_fee': pnl_no_fee,
            'entry_fee': entry_fee,
            'exit_fee': exit_fee,
            'total_fee': total_fee,
            'fee_rate': fee_rate,
            'balance_after_trade': balance_after_trade,
            'trade_amount_percent': trade_amount_percent,
            'position_value': position_value,
            'position_value_no_fee': position_value_no_fee,
            'duration_seconds': duration_seconds,
            'price_change_percent': price_change_percent,
            'margin': margin,
            'margin_no_fee': margin_no_fee
        }
    

    # open short processes
    def open_short(self, open_prices, open_times,
                    balance, balance_without_fee, first_balance,
                    trade_amount_percent, margin_balance, leverage):

        entry_price = open_prices

        balance_before_trade = balance
        balance_before_trade_no_fee = balance_without_fee

        # ---------- Margin ----------
        margin = calculate_margin(balance, self.tactical_balance, trade_amount_percent)

        # ---------- Leverage ----------
        leverage = self._select_leverage(balance)

        position_value = margin * leverage
        position_size = position_value / entry_price

        margin_no_fee = calculate_margin(
            balance_without_fee, self.tactical_balance, trade_amount_percent
        )
        position_value_no_fee = margin_no_fee * leverage
        position_size_no_fee = position_value_no_fee / entry_price

        # update balance after allocating margin
        balance -= margin
        balance_without_fee -= margin_no_fee

        # update open time and current position
        open_time_value = open_times
        current_position = "short"

        print("Open SHORT at price:", entry_price, "$", "| Open Time:", open_time_value, "| leverage:", leverage)

        return {
            'entry_price': entry_price,
            'balance': balance,
            'balance_without_fee': balance_without_fee,
            'balance_before_trade': balance_before_trade,
            'balance_before_trade_no_fee': balance_before_trade_no_fee,
            'margin': margin,
            'leverage': leverage,
            'position_value': position_value,
            'position_size': position_size,
            'margin_no_fee': margin_no_fee,
            'position_value_no_fee': position_value_no_fee,
            'position_size_no_fee': position_size_no_fee,
            'open_time_value': open_time_value,
            'current_position': current_position
        }


    # close short processes
    def close_short(self, open_prices, open_times,
            entry_price, position_size, position_size_no_fee,
            fee_rate, margin, margin_no_fee,
            balance, balance_without_fee,
            balance_before_trade, balance_before_trade_no_fee,
            deducting_fee_total, profits_lst, total_profit_percent,
            count_closed_orders, equity_curve,
            max_drawdown, total_wins, total_wins_short, total_losses,
            total_short, cooldown_after_big_pnl, leverage,
            cooldown_until_index, open_time_value, csv_logger, trade_amount_percent, profit_percent_per_month,
            save_money, trade_power):

        close_price = open_prices

        # PnL
        metrics = calculate_trade_metrics(
            "short", entry_price, close_price, position_size, margin, fee_rate,
            balance_before_trade,
        )
        pnl = metrics["pnl"]
        pnl_no_fee = position_size_no_fee * (entry_price - close_price)

        # Fee like Toobit
        entry_fee = metrics["entry_fee"]
        exit_fee = metrics["exit_fee"]
        total_fee = metrics["total_fee"]

        # Update balance
        balance += margin + pnl - total_fee
        balance_without_fee += margin_no_fee + pnl_no_fee

        # profit after fee
        profit = metrics["profit"]
        profit_percent = metrics["profit_percent"]
        profit_percent_per_month = accumulate_monthly_profit_percent(
            profit_percent_per_month,
            profit_percent,
        )
        pnl_percent = metrics["pnl_percent"]
        balance_after_trade = balance
        position_value = entry_price * position_size
        position_value_no_fee = entry_price * position_size_no_fee
        price_change_percent = (entry_price - close_price) * 100 / entry_price

        deducting_fee_total += total_fee
        profits_lst.append(profit)
        total_profit_percent += profit_percent
        count_closed_orders += 1

        equity_curve.append(balance + save_money)
        # ---- calculate max drawdown ----
        peak = max(equity_curve)
        drawdown = (balance + save_money - peak) / peak * 100
        max_drawdown = min(max_drawdown, drawdown)

        # ---- count wins and losses ----
        if profit_percent > 0:
            total_wins += 1
            total_wins_short += 1
        else:
            total_losses += 1

        # ---- count shorts ----
        total_short += 1

        # ---- COOLDOWN AFTER BIG PROFIT ----
        pnl_percent_without_leverage = ((pnl / margin) * 100) / leverage
        if pnl_percent_without_leverage >= 4:
            cooldown_until_index = 0 + cooldown_after_big_pnl
            print(f"🟡 Cooldown Activated (SHORT) until candle index {cooldown_until_index}")

        close_time_value = open_times
        days, hours, minutes = trade_duration(open_time_value, close_time_value)
        duration_seconds = days * 86400 + hours * 3600 + minutes * 60


        print("Close SHORT at price:", close_price, "$", "| Close Time:", close_time_value, "| leverage:", leverage)
        print("Balance:", round(balance_before_trade, 2), "$", "→", round(balance, 2), "$", "| Save Money:", round(save_money, 2), "$")
        print("Balance (no fee):",
            round(balance_before_trade_no_fee, 2), "$", "→", round(balance_without_fee, 2), "$")
        print("pnl:", round(pnl, 2), "$ |", round(pnl_percent, 2), "% |", "Amount:", round(margin), "$")
        print("fee:", round(total_fee, 2), "$")
        print("Profit:", round(profit, 2), "$ |", round(profit_percent, 2), "%")
        print(f"Trade Duration: {days} days, {hours} hours, {minutes} minutes")
        print("-" * 90)

        csv_logger.log_trade(
            "SHORT",
            open_time_value,
            close_time_value,
            entry_price,
            close_price,
            round(balance_before_trade, 2),
            round(balance, 2),
            round(margin , 2),
            leverage,
            trade_amount_percent,
            round(profit, 2),
            round(profit_percent, 2),
            round(pnl_percent, 2),
            round(total_fee, 4),
            days,
            hours,
            minutes,
            save_money,
            profit_percent_per_month
        )

        # ---- save money ----
        if balance < self.tactical_balance * 75 / 100:
            if save_money >= self.tactical_balance * 25 / 100:
                balance += self.tactical_balance * 25 / 100
                save_money -= self.tactical_balance * 25 / 100

        # stop trade if we got monthly threshold for this month
        if self.monthly_close_filter == True :
            if profit_percent_per_month >= self.monthly_profit_percent_stop_trade:
                self.tactical_balance = self.tactical_balance + (self.tactical_balance * self.monthly_compound / 100)
                save_money += balance - self.tactical_balance
                balance = self.tactical_balance
                cooldown_until_index = 0
                trade_power = False    # off
        else:
            if balance >= self.tactical_balance * 1.08:
                self.tactical_balance = balance
            
        current_position = None

        return {
            'balance': balance,
            'balance_without_fee': balance_without_fee,
            'deducting_fee_total': deducting_fee_total,
            'profits_lst': profits_lst,
            'total_profit_percent': total_profit_percent,
            'count_closed_orders': count_closed_orders,
            'equity_curve': equity_curve,
            'max_drawdown': max_drawdown,
            'total_wins': total_wins,
            'total_wins_short': total_wins_short,
            'total_losses': total_losses,
            'total_short': total_short,
            'cooldown_until_index': cooldown_until_index,
            'current_position': current_position,
            'trade_power': trade_power,
            'profit_percent_per_month': profit_percent_per_month,
            'save_money' : save_money,
            'profit': profit,
            'profit_percent': profit_percent,
            'pnl': pnl,
            'pnl_percent': pnl_percent,
            'pnl_no_fee': pnl_no_fee,
            'entry_fee': entry_fee,
            'exit_fee': exit_fee,
            'total_fee': total_fee,
            'fee_rate': fee_rate,
            'balance_after_trade': balance_after_trade,
            'trade_amount_percent': trade_amount_percent,
            'position_value': position_value,
            'position_value_no_fee': position_value_no_fee,
            'duration_seconds': duration_seconds,
            'price_change_percent': price_change_percent,
            'margin': margin,
            'margin_no_fee': margin_no_fee
        }
