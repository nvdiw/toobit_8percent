import os

import requests


class TelegramNotifier:
    def __init__(self, bot_token, chat_id, default_symbol="BTCUSDT"):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.default_symbol = default_symbol
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_open_long(self, price, time_str, symbol=None, margin=None, position_size=None, leverage=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"🚀 <b>OPEN LONG</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if margin is not None and position_size is not None and leverage is not None:
            message += f"\n💸 Margin: {margin} $ | Size: {position_size:.6f} | Leverage: {leverage}x"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        requests.post(self.base_url, data=payload)

    def send_close_long(
        self,
        price,
        time_str,
        symbol=None,
        reason=None,
        profit=None,
        profit_percent=None,
        pnl=None,
        pnl_percent=None,
        balance_before=None,
        balance_after=None,
        margin=None,
    ):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"❌ <b>CLOSE LONG</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if pnl is not None and pnl_percent is not None:
            message += f"\n📈 P/L: {round(pnl, 2)} $ | ({round(pnl_percent, 2)} %)"

        if margin is not None:
            message += f"\n📈 Amount: {round(margin, 2)} $ in position"

        if profit is not None and profit_percent is not None:
            message += "\n\n total Portfolio (Calculating fees)"
            message += f"\n📈 Profit: {round(profit, 2)} $ | ({round(profit_percent, 2)} %)"

        if balance_before is not None and balance_after is not None:
            message += f"\n💵 Balance: {round(balance_before, 2)} $ → {round(balance_after, 2)} $"

        if reason:
            message += f"\n📉 Reason: {reason}"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        requests.post(self.base_url, data=payload)

    def send_open_short(self, price, time_str, symbol=None, margin=None, position_size=None, leverage=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"🔻 <b>OPEN SHORT</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if margin is not None and position_size is not None and leverage is not None:
            message += f"\n💸 Margin: {margin} $ | Size: {position_size:.6f} | Leverage: {leverage}x"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        requests.post(self.base_url, data=payload)

    def send_close_short(
        self,
        price,
        time_str,
        symbol=None,
        reason=None,
        profit=None,
        profit_percent=None,
        pnl=None,
        pnl_percent=None,
        balance_before=None,
        balance_after=None,
        margin=None,
    ):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"❌ <b>CLOSE SHORT</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if pnl is not None and pnl_percent is not None:
            message += f"\n📈 P/L: {round(pnl, 2)} $ | ({round(pnl_percent, 2)} %)"

        if margin is not None:
            message += f"\n📈 Amount: {round(margin, 2)} $ in position"

        if profit is not None and profit_percent is not None:
            message += "\n\n total Portfolio (Calculating fees)"
            message += f"\n📈 Profit: {round(profit, 2)} $ | ({round(profit_percent, 2)} %)"

        if balance_before is not None and balance_after is not None:
            message += f"\n💵 Balance: {round(balance_before, 2)} $ → {round(balance_after, 2)} $"

        if reason:
            message += f"\n📉 Reason: {reason}"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        requests.post(self.base_url, data=payload)


def load_telegram_config():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if bot_token and chat_id:
        try:
            return bot_token.strip(), int(chat_id)
        except Exception:
            raise RuntimeError("Invalid TELEGRAM_CHAT_ID env var; must be integer.")

    raise RuntimeError(
        "Telegram config not found in environment. "
        "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (for example via .env)."
    )


def create_telegram_notifier(default_symbol="BTCUSDT"):
    bot_token, chat_id = load_telegram_config()
    return TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        default_symbol=default_symbol,
    )
