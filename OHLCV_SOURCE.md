# انتخاب منبع کندل

گزینهٔ `--ohlcv-source binance` یا `--ohlcv-source toobit` فقط منبع OHLCV را انتخاب می‌کند. موجودی، پوزیشن‌ها، لوریج، سفارش بازکردن و بستن و حالت Future/Copy همگی همچنان با Toobit کار می‌کنند. در صورت قطع‌شدن منبع منتخب، ربات به صرافی دیگر تغییر نمی‌کند.

## تست اتصال بدون معامله

از داخل پوشهٔ هر پروژه اجرا کنید:

```powershell
python get_ohlcv.py --ohlcv-source binance --symbol BTCUSDT --interval 15m --limit 201
python get_ohlcv.py --ohlcv-source toobit --symbol BTCUSDT --interval 15m --limit 201
```

این کامند فقط کندل عمومی دریافت می‌کند؛ به کلید API، دیتابیس یا اجرای ربات نیاز ندارد. موفقیت با JSON شامل `source` و `candles` و exit code صفر مشخص می‌شود. خطا exit code یک دارد.

## اجرای ربات

آرگومان را به کامند معمول اجرای خودتان اضافه کنید و `--api-trade` و بقیهٔ گزینه‌های قبلی را نگه دارید:

```powershell
# magnal (Django runner)
python manage.py runbot --ohlcv-source binance
# magnal (legacy standalone)
python ma_strategy.py --ohlcv-source binance
# toobit_8percent
python get_info.py --ohlcv-source binance
```

برای انتخاب Toobit، مقدار `binance` را با `toobit` جایگزین کنید. این سه کامند ربات را اجرا می‌کنند و ممکن است سفارش واقعی بفرستند؛ تست اتصال را با `get_ohlcv.py` انجام دهید.

runnerهای جدید magnal هم آرگومان را می‌پذیرند:

```powershell
python manage.py runmaster --strategy ma --ohlcv-source binance
python manage.py runmasters --ohlcv-source binance
```

انتخاب جدید با راه‌اندازی مجدد همان پروسه اعمال می‌شود؛ supervisor پروسهٔ در حال اجرا را عوض نمی‌کند. اجرای هم‌زمان دو نسخهٔ ربات مناسب نیست.

## سابقهٔ runner جدید magnal

پیش‌فرض ربات‌های legacy همچنان Toobit است. runner جدید منبع ذخیره‌شده را پس از restart حفظ می‌کند؛ برای runtime جدید یا قدیمی فاقد این مشخصه، پیش‌فرض Binance است.

تغییر منبع runtime جدید دارای سابقه نیاز به `--reset-flat` دارد و فقط پس از تسویهٔ تمام پوزیشن‌ها و سفارش‌های حل‌نشده پذیرفته می‌شود. این گزینه تاریخچهٔ کندل و checkpoint را برای منبع جدید پاک می‌کند. برای تست اتصال نیازی به این گزینه نیست.

Binance از میزبان عمومی مخصوص دادهٔ بازار `https://data-api.binance.vision/api/v3/klines` خوانده می‌شود. این میزبان مستقل از API اجرای سفارش است: [مستندات رسمی Binance](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md).

در صفحه‌بندی تاریخچهٔ Toobit هر دو `startTime` و `endTime` فرستاده می‌شوند؛ در بررسی واقعی `startTime` به‌تنهایی رعایت نشد، اما بازهٔ کامل درست پاسخ داد: [مستندات عمومی کندل Toobit](https://api-docs.toobit.com/api/spot-market-data).
