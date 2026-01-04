import requests

class TelegramNotifier:
    def __init__(self, bot_token, chat_id, default_symbol="BTCUSDT"):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.default_symbol = default_symbol
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"


    def send_open_long(self, price, time_str, symbol=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"🚀 <b>OPEN LONG</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        requests.post(self.base_url, data=payload)


    def send_close_long(self, price, time_str, symbol=None, reason=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"❌ <b>CLOSE LONG</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if reason:
            message += f"\n📉 Reason: {reason}"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        requests.post(self.base_url, data=payload)


    def send_open_short(self, price, time_str, symbol=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"🔻 <b>OPEN SHORT</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        requests.post(self.base_url, data=payload)


    def send_close_short(self, price, time_str, symbol=None, reason=None):
        if symbol is None:
            symbol = self.default_symbol

        message = (
            f"❌ <b>CLOSE SHORT</b>\n"
            f"💰 Price: <b>{price} $</b>\n"
            f"🕒 Time: {time_str}\n"
            f"📊 Symbol: {symbol}"
        )

        if reason:
            message += f"\n📉 Reason: {reason}"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        requests.post(self.base_url, data=payload)
