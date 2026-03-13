"""
روزنامة السوق الذكية
يحدد لكل رمز هل سوقه مفتوح الآن أم لا
مع الأخذ بعين الاعتبار: المنطقة الزمنية، العطل، جلسات التداول
"""

from datetime import datetime, time, date
import pytz


# ============================================================
# العطل الرسمية لسوق NYSE / NASDAQ 2024-2026
# ============================================================
US_HOLIDAYS = {
    # 2024
    date(2024,  1,  1), date(2024,  1, 15), date(2024,  2, 19),
    date(2024,  3, 29), date(2024,  5, 27), date(2024,  6, 19),
    date(2024,  7,  4), date(2024,  9,  2), date(2024, 11, 28),
    date(2024, 12, 25),
    # 2025
    date(2025,  1,  1), date(2025,  1, 20), date(2025,  2, 17),
    date(2025,  4, 18), date(2025,  5, 26), date(2025,  6, 19),
    date(2025,  7,  4), date(2025,  9,  1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026,  1,  1), date(2026,  1, 19), date(2026,  2, 16),
    date(2026,  4,  3), date(2026,  5, 25), date(2026,  6, 19),
    date(2026,  7,  3), date(2026,  8, 31), date(2026, 11, 26),
    date(2026, 12, 25),
}

# ============================================================
# تصنيف الأسواق
# ============================================================
MARKET_PROFILES = {
    "crypto"    : {"always_open": True},
    "forex"     : {"always_open": False,
                   "open_days"  : [0,1,2,3,4],      # الإثنين–الجمعة
                   "open_time"  : time(21, 0),        # UTC أحد 21:00
                   "close_time" : time(21, 0),        # UTC جمعة 21:00
                   "note"       : "فوركس يغلق عطلة نهاية الأسبوع فقط"},
    "stock"     : {"always_open": False,
                   "tz"         : "America/New_York",
                   "open_days"  : [0,1,2,3,4],
                   "open_time"  : time(9, 30),
                   "close_time" : time(16, 0),
                   "holidays"   : US_HOLIDAYS},
    "index"     : {"always_open": False,
                   "tz"         : "America/New_York",
                   "open_days"  : [0,1,2,3,4],
                   "open_time"  : time(9, 30),
                   "close_time" : time(16, 0),
                   "holidays"   : US_HOLIDAYS},
    "commodity" : {"always_open": False,
                   "tz"         : "America/New_York",
                   "open_days"  : [0,1,2,3,4],
                   "open_time"  : time(9, 0),
                   "close_time" : time(17, 30),
                   "holidays"   : US_HOLIDAYS},
}


# ============================================================
# تحديد نوع الأصل من رمزه
# ============================================================
def _detect_type(symbol: str) -> str:
    s = symbol.upper()
    if "/" in s and "USDT" in s: return "crypto"
    if "=X"  in s:               return "forex"
    if "=F"  in s:               return "commodity"
    if s.startswith("^"):        return "index"
    return "stock"


# ============================================================
# الدالة الرئيسية
# ============================================================
def is_market_open(symbol: str, now_utc: datetime = None) -> dict:
    """
    هل سوق هذا الرمز مفتوح الآن؟

    Returns:
        {
          "open"        : bool,
          "reason"      : str,
          "next_open"   : str,   # متى يفتح (إذا مغلق)
          "session"     : str,   # اسم الجلسة
          "minutes_left": int,   # كم دقيقة حتى يغلق (إذا مفتوح)
        }
    """
    if now_utc is None:
        now_utc = datetime.now(pytz.utc)

    asset_type = _detect_type(symbol)
    profile    = MARKET_PROFILES.get(asset_type, MARKET_PROFILES["stock"])

    # كريبتو: مفتوح دائماً
    if profile.get("always_open"):
        return {
            "open"        : True,
            "reason"      : "كريبتو — مفتوح 24/7 🟢",
            "next_open"   : None,
            "session"     : "24/7",
            "minutes_left": 9999,
        }

    # فوركس: مفتوح كل أيام العمل
    if asset_type == "forex":
        weekday = now_utc.weekday()
        # يغلق جمعة 21:00 UTC حتى أحد 21:00 UTC
        if weekday == 5:   # سبت
            return _closed("فوركس مغلق — عطلة نهاية الأسبوع",
                           "الأحد 21:00 UTC")
        if weekday == 6 and now_utc.time() < time(21, 0):
            return _closed("فوركس مغلق — عطلة نهاية الأسبوع",
                           f"اليوم {21 - now_utc.hour} ساعة")
        minutes_left = _minutes_to_friday_close(now_utc)
        return {
            "open"        : True,
            "reason"      : "فوركس مفتوح 🟢",
            "next_open"   : None,
            "session"     : _forex_session(now_utc),
            "minutes_left": minutes_left,
        }

    # أسهم / سلع / مؤشرات
    tz_name  = profile.get("tz", "America/New_York")
    tz       = pytz.timezone(tz_name)
    now_local= now_utc.astimezone(tz)
    weekday  = now_local.weekday()
    today    = now_local.date()

    # عطلة نهاية الأسبوع
    if weekday not in profile["open_days"]:
        next_open = _next_weekday(today, profile, tz)
        return _closed(
            f"السوق مغلق — عطلة {'السبت' if weekday==5 else 'الأحد'}",
            next_open
        )

    # عطلة رسمية
    holidays = profile.get("holidays", set())
    if today in holidays:
        next_open = _next_weekday(today, profile, tz, skip_today=True)
        return _closed("السوق مغلق — عطلة رسمية 🏖️", next_open)

    # ساعات التداول
    open_t  = profile["open_time"]
    close_t = profile["close_time"]
    cur_t   = now_local.time()

    if cur_t < open_t:
        mins = int((
            datetime.combine(today, open_t) -
            datetime.combine(today, cur_t)
        ).total_seconds() / 60)
        return _closed(
            f"السوق لم يفتح بعد — يفتح {open_t.strftime('%H:%M')} ({tz_name})",
            f"بعد {mins} دقيقة"
        )

    if cur_t >= close_t:
        next_open = _next_weekday(today, profile, tz, skip_today=True)
        return _closed(
            f"السوق أغلق — أغلق {close_t.strftime('%H:%M')} ({tz_name})",
            next_open
        )

    # السوق مفتوح — كم دقيقة متبقية
    mins_left = int((
        datetime.combine(today, close_t) -
        datetime.combine(today, cur_t)
    ).total_seconds() / 60)

    return {
        "open"        : True,
        "reason"      : f"السوق مفتوح 🟢 — يغلق {close_t.strftime('%H:%M')} {tz_name}",
        "next_open"   : None,
        "session"     : asset_type.upper(),
        "minutes_left": mins_left,
    }


# ============================================================
# فلترة قائمة رموز — أعد المفتوحة فقط
# ============================================================
def filter_open_symbols(symbols: list, now_utc: datetime = None) -> dict:
    """
    يصنّف الرموز إلى مفتوح / مغلق

    Returns:
        {
          "open"  : [(symbol, info), ...],
          "closed": [(symbol, info), ...],
          "summary": str
        }
    """
    if now_utc is None:
        now_utc = datetime.now(pytz.utc)

    open_list   = []
    closed_list = []

    for symbol in symbols:
        info = is_market_open(symbol, now_utc)
        if info["open"]:
            open_list.append((symbol, info))
        else:
            closed_list.append((symbol, info))

    total   = len(symbols)
    n_open  = len(open_list)
    n_close = len(closed_list)

    summary = (
        f"✅ {n_open}/{total} أسواق مفتوحة"
        if n_open > 0
        else f"💤 جميع الأسواق ({total}) مغلقة الآن"
    )

    return {
        "open"   : open_list,
        "closed" : closed_list,
        "summary": summary,
        "any_open": n_open > 0,
    }


# ============================================================
# أدوات مساعدة
# ============================================================
def _closed(reason: str, next_open: str) -> dict:
    return {
        "open"        : False,
        "reason"      : reason,
        "next_open"   : next_open,
        "session"     : "مغلق",
        "minutes_left": 0,
    }


def _next_weekday(today, profile, tz, skip_today=False) -> str:
    """يجد اليوم التالي الذي يكون فيه السوق مفتوحاً"""
    from datetime import timedelta
    holidays = profile.get("holidays", set())
    open_days= profile["open_days"]
    open_t   = profile["open_time"]

    check = today + timedelta(days=1 if skip_today else 0)
    for _ in range(10):
        if check.weekday() in open_days and check not in holidays:
            return f"{check.strftime('%A %Y-%m-%d')} {open_t.strftime('%H:%M')} {tz.zone}"
        check += timedelta(days=1)
    return "قريباً"


def _forex_session(now_utc: datetime) -> str:
    """تحديد الجلسة الحالية للفوركس"""
    h = now_utc.hour
    if  0 <= h <  7: return "جلسة طوكيو 🇯🇵"
    if  7 <= h <  8: return "جلسة لندن تفتح 🇬🇧"
    if  8 <= h < 12: return "جلسة لندن 🇬🇧"
    if 12 <= h < 13: return "لندن + نيويورك (تداخل 🔥)"
    if 13 <= h < 17: return "جلسة نيويورك 🇺🇸"
    if 17 <= h < 22: return "نيويورك تغلق / هادئ"
    return "ما بين الجلسات"


def _minutes_to_friday_close(now_utc: datetime) -> int:
    """كم دقيقة حتى إغلاق الفوركس (جمعة 21:00 UTC)"""
    from datetime import timedelta
    weekday = now_utc.weekday()
    days_to_friday = (4 - weekday) % 7
    friday_close = now_utc.replace(
        hour=21, minute=0, second=0, microsecond=0
    ) + timedelta(days=days_to_friday)
    delta = friday_close - now_utc
    return max(0, int(delta.total_seconds() / 60))
