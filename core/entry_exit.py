"""
حاسبة مناطق الدخول والخروج
مبنية على: ATR + دعم/مقاومة + Bollinger
تدعم: متداول يومي (ساعات) + سوينغ (أيام)
"""


def calculate_entry_exit(
    direction  : str,   # BUY / SELL
    price      : float,
    indicators : dict,
) -> dict:
    """
    تحسب مناطق الدخول والخروج بطريقتين:
      - يومي  (Day): هوامش ضيقة، ATR × 0.5 / 1.5 / 2.5
      - سوينغ (Swing): هوامش أوسع، ATR × 1 / 2 / 3
    """
    atr_pct = indicators.get("atr_pct", 1.0)   # % من السعر
    atr     = price * atr_pct / 100             # قيمة ATR بالعملة

    sr      = indicators.get("sr", {})
    bb_up   = indicators.get("bb_upper", price * 1.02)
    bb_low  = indicators.get("bb_lower", price * 0.98)

    support    = sr.get("nearest_support")
    resistance = sr.get("nearest_resistance")

    if direction == "BUY":
        result = _buy_zones(price, atr, support, resistance, bb_low, bb_up)
    elif direction == "SELL":
        result = _sell_zones(price, atr, support, resistance, bb_low, bb_up)
    else:
        return {"available": False}

    result["direction"] = direction
    result["available"] = True
    return result


# ============================================================
# BUY — مناطق الشراء
# ============================================================
def _buy_zones(price, atr, support, resistance, bb_low, bb_up):
    # --- منطقة الدخول ---
    # نشتري قريباً من السعر الحالي، أو عند ارتداد صغير
    entry_ideal = round(price, 4)                        # السعر الحالي
    entry_low   = round(price - atr * 0.5, 4)           # عند تراجع نصف ATR
    entry_high  = round(price + atr * 0.3, 4)           # حد أقصى للدخول

    # --- وقف الخسارة ---
    # نضعه تحت أقرب دعم بهامش ATR × 0.5
    # إذا لم يوجد دعم: تحت السعر بـ ATR × 1.5
    if support and support > price * 0.90:
        sl_day   = round(support - atr * 0.3, 4)        # يومي: ضيق
        sl_swing = round(support - atr * 0.6, 4)        # سوينغ: أوسع
    else:
        sl_day   = round(price - atr * 1.5, 4)
        sl_swing = round(price - atr * 2.5, 4)

    # --- الأهداف ---
    # TP1: أقرب مقاومة أو ATR × 1.5
    # TP2: ATR × 2.5 أو BB العلوي
    # TP3: ATR × 4

    if resistance and resistance < price * 1.15:
        tp1_day   = round(min(resistance * 0.998, price + atr * 1.5), 4)
        tp1_swing = round(min(resistance * 0.998, price + atr * 2.0), 4)
    else:
        tp1_day   = round(price + atr * 1.5, 4)
        tp1_swing = round(price + atr * 2.0, 4)

    tp2_day   = round(max(price + atr * 2.5, bb_up), 4)
    tp2_swing = round(price + atr * 3.5, 4)

    tp3_swing = round(price + atr * 5.0, 4)

    # --- نسبة R/R ---
    rr_day   = _rr(price, sl_day,   tp1_day)
    rr_swing = _rr(price, sl_swing, tp1_swing)

    return {
        "entry": {
            "ideal": entry_ideal,
            "zone" : f"{entry_low} — {entry_high}",
            "note" : "ادخل فوراً أو انتظر تراجعاً بسيطاً"
        },
        "day": {
            "sl"    : sl_day,
            "tp1"   : tp1_day,
            "tp2"   : tp2_day,
            "rr"    : rr_day,
            "label" : "يومي (ساعات)"
        },
        "swing": {
            "sl"    : sl_swing,
            "tp1"   : tp1_swing,
            "tp2"   : tp2_swing,
            "tp3"   : tp3_swing,
            "rr"    : rr_swing,
            "label" : "سوينغ (أيام)"
        },
        "risk_pct": round((price - sl_day) / price * 100, 2),
    }


# ============================================================
# SELL — مناطق البيع (عكس الشراء تماماً)
# ============================================================
def _sell_zones(price, atr, support, resistance, bb_low, bb_up):
    entry_ideal = round(price, 4)
    entry_high  = round(price + atr * 0.5, 4)
    entry_low   = round(price - atr * 0.3, 4)

    if resistance and resistance < price * 1.10:
        sl_day   = round(resistance + atr * 0.3, 4)
        sl_swing = round(resistance + atr * 0.6, 4)
    else:
        sl_day   = round(price + atr * 1.5, 4)
        sl_swing = round(price + atr * 2.5, 4)

    if support and support > price * 0.85:
        tp1_day   = round(max(support * 1.002, price - atr * 1.5), 4)
        tp1_swing = round(max(support * 1.002, price - atr * 2.0), 4)
    else:
        tp1_day   = round(price - atr * 1.5, 4)
        tp1_swing = round(price - atr * 2.0, 4)

    tp2_day   = round(min(price - atr * 2.5, bb_low), 4)
    tp2_swing = round(price - atr * 3.5, 4)
    tp3_swing = round(price - atr * 5.0, 4)

    rr_day   = _rr(price, sl_day,   tp1_day,   sell=True)
    rr_swing = _rr(price, sl_swing, tp1_swing, sell=True)

    return {
        "entry": {
            "ideal": entry_ideal,
            "zone" : f"{entry_low} — {entry_high}",
            "note" : "بيع فوراً أو انتظر ارتداداً بسيطاً"
        },
        "day": {
            "sl"    : sl_day,
            "tp1"   : tp1_day,
            "tp2"   : tp2_day,
            "rr"    : rr_day,
            "label" : "يومي (ساعات)"
        },
        "swing": {
            "sl"    : sl_swing,
            "tp1"   : tp1_swing,
            "tp2"   : tp2_swing,
            "tp3"   : tp3_swing,
            "rr"    : rr_swing,
            "label" : "سوينغ (أيام)"
        },
        "risk_pct": round((sl_day - price) / price * 100, 2),
    }


# ============================================================
# حساب نسبة المخاطرة/العائد
# ============================================================
def _rr(entry, sl, tp, sell=False):
    try:
        if not sell:
            risk   = abs(entry - sl)
            reward = abs(tp - entry)
        else:
            risk   = abs(sl - entry)
            reward = abs(entry - tp)
        if risk == 0:
            return "N/A"
        ratio = reward / risk
        return f"1:{ratio:.1f}"
    except:
        return "N/A"
