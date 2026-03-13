"""
نظام إرسال الإشارات عبر تيليغرام
"""

import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def send_telegram(message: str) -> bool:
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("⚠️ مفاتيح تيليغرام غير موجودة")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text"   : message,
            },
            timeout=10
        )
        if r.status_code != 200:
            print(f"⚠️ تيليغرام رفض الرسالة: {r.status_code} — {r.text[:100]}")
        return r.status_code == 200
    except Exception as e:
        print(f"خطأ في تيليغرام: {e}")
        return False


def format_consensus_signal(
    symbol     : str,
    consensus  : dict,
    risk       : dict,
    market_data: dict,
    liquidity  : dict = None,
    entry_exit : dict = None
) -> str:
    """
    تنسيق إشارة الإجماع الكاملة
    """
    now = datetime.utcnow().strftime("%H:%M UTC | %Y-%m-%d")
    ind = market_data.get("indicators", {})

    # تقارير الوكلاء — مكثفة ومنظمة (تيليغرام)
    openings = consensus.get("openings", {})
    agents_lines = []
    for key, op in openings.items():
        struct = op.get("structured", {})
        stance = op.get("stance", "")
        s_icon = "🟢" if stance == "BUY" else "🔴" if stance == "SELL" else "🟡"
        if struct:
            agents_lines.append(
                f"   {s_icon} *{op['name']}*\n"
                f"      📌 {struct.get('السبب', struct.get('أقوى دليل', ''))}"
            )
        else:
            agents_lines.append(
                f"   {s_icon} *{op['name']}:* {stance}"
            )
    reasons = "\n".join(agents_lines)

    # حجة القاضي الفاصلة
    judge_text = ""
    if consensus.get("judge_reasoning"):
        judge_text = f"\n🏛️ *حكم القاضي:* _{consensus['judge_reasoning'][:120]}_"

    # أقوى حجة فائزة
    winning_text = ""
    if consensus.get("winning_argument"):
        winning_text = f"\n💡 *الحجة الفاصلة:* _{consensus['winning_argument'][:100]}_"

    # من غيّر رأيه؟
    mind_change_text = ""
    mc = consensus.get("mind_changes", 0)
    if mc > 0:
        mind_change_text = f"\n🔄 *غيّر رأيه خلال النقاش:* {mc} وكيل"

    # المعارضون
    dissenter_text = ""
    if consensus.get("dissent_summary"):
        dissenter_text = f"\n⚡ *أقوى اعتراض:* _{consensus['dissent_summary'][:100]}_"
    for d in consensus.get("dissenters", []):
        dissenter_text += f"\n   ↳ {d['agent_name']} → {d['vote']}"

    # تأكيد 15M
    conf_15m      = consensus.get("confirmation_15m", {})
    conf_15m_text = ""
    if conf_15m.get("available"):
        delta = conf_15m.get("confidence_delta", 0)
        delta_str = f"({'+' if delta >= 0 else ''}{delta}%)" if delta != 0 else ""
        conf_15m_text = (
            f"\n⏱️ *تأكيد 15M:* {conf_15m['label']} {delta_str}"
            f"\n   RSI={conf_15m.get('rsi_15m','N/A')} | "
            f"MA20={'✅' if conf_15m.get('above_ma20') else '❌'} | "
            f"MACD={'✅' if conf_15m.get('macd_positive') else '❌'}"
        )
    elif conf_15m:
        conf_15m_text = f"\n⏱️ *تأكيد 15M:* {conf_15m.get('label','غير متاح')}"

    # ============================================================
    # قسم مناطق الدخول والخروج
    # ============================================================
    ee_text = ""
    if entry_exit and entry_exit.get("available"):
        entry  = entry_exit.get("entry", {})
        day    = entry_exit.get("day",   {})
        swing  = entry_exit.get("swing", {})
        riskp  = entry_exit.get("risk_pct", "N/A")

        ee_text = f"""
{'─'*34}
🎯 *مناطق الدخول والخروج*
   💰 السعر المثالي: `{entry.get('ideal','N/A')}`
   📍 منطقة الدخول: `{entry.get('zone','N/A')}`
   _{entry.get('note','')}_
{'─'*34}
📅 *يومي (ساعات)* — R/R: `{day.get('rr','N/A')}`
   🛑 وقف الخسارة: `{day.get('sl','N/A')}` ({riskp}%)
   🎯 هدف 1 (TP1): `{day.get('tp1','N/A')}`
   🎯 هدف 2 (TP2): `{day.get('tp2','N/A')}`
{'─'*34}
📆 *سوينغ (أيام)* — R/R: `{swing.get('rr','N/A')}`
   🛑 وقف الخسارة: `{swing.get('sl','N/A')}`
   🎯 هدف 1 (TP1): `{swing.get('tp1','N/A')}`
   🎯 هدف 2 (TP2): `{swing.get('tp2','N/A')}`
   🎯 هدف 3 (TP3): `{swing.get('tp3','N/A')}`"""

    # بيانات المؤشرات المتقدمة
    adx  = ind.get("adx", {})
    sr   = ind.get("sr", {})
    pat  = ind.get("patterns", {})

    # تعدد الأطر
    mtf_text = ""
    mtf_alignment = consensus.get("mtf_alignment", "")
    mtf_frames    = consensus.get("mtf_frames", {})
    if mtf_frames:
        lines = []
        for label, data in mtf_frames.items():
            lines.append(
                f"\n   {label}: {data.get('trend','N/A')} "
                f"(RSI={data.get('rsi','N/A')})"
            )
        lines.append(f"\n   التوافق: *{mtf_alignment}*")
        mtf_text = "".join(lines)
    elif mtf_alignment:
        mtf_text = f" {mtf_alignment}"

    # الأنماط المكتشفة — قائمة بنقاط
    patterns_text = ""
    if pat.get("detected"):
        patterns_text = "\n".join(
            f"   • {p}" for p in pat["detected"][:4]
        )

    # بيانات المخاطر
    var_data   = risk.get("var", {})
    kelly_data = risk.get("kelly", {})
    var_str    = f"{var_data.get('var', 'N/A')}%" if var_data.get("available") else "N/A"
    cvar_str   = f"{var_data.get('cvar', 'N/A')}%" if var_data.get("available") else "N/A"
    kelly_str  = f"{kelly_data.get('recommended', 15)}%"

    # السيولة (للكريبتو)
    liquidity_text = ""
    if liquidity and liquidity.get("available"):
        liquidity_text = (
            f"\n💧 *السيولة:* {liquidity.get('pressure', 'N/A')}"
            f" (Spread: {liquidity.get('spread_pct', 'N/A')}%)"
        )

    # تحذيرات المخاطر
    warnings = risk.get("warnings", [])
    warnings_text = ""
    if warnings:
        warnings_text = "\n⚠️ *تحذيرات:*\n" + "\n".join(
            f"   • {w}" for w in warnings
        )

    return (
        f"{'─'*34}\n"
        f"{consensus['emoji']} اشارة: {consensus['direction']}\n"
        f"{'─'*34}\n"
        f"الاصل: {symbol} ({market_data.get('type','').upper()})\n"
        f"السعر: {market_data.get('price', 'N/A')}\n"
        f"التغير 24h: {market_data.get('change_24h', 0):+.2f}%\n"
        f"{'─'*34}\n"
        f"نتيجة النقاش\n"
        f"الحكم: {consensus['votes']} — {consensus['strength']}\n"
        f"الثقة: {consensus['avg_confidence']}%\n"
        f"{conf_15m_text}\n"
        f"{judge_text}\n"
        f"{winning_text}\n"
        f"{mind_change_text}\n"
        f"{'─'*34}\n"
        f"المتفقون مع القرار:\n"
        f"{reasons}\n"
        f"{dissenter_text}\n"
        f"{ee_text}\n"
        f"{'─'*34}\n"
        f"المؤشرات التقنية\n"
        f"  MA20={ind.get('ma20','N/A')} | MA50={ind.get('ma50','N/A')} | MA200={ind.get('ma200','N/A')}\n"
        f"  RSI={ind.get('rsi','N/A')} | MACD={ind.get('macd_hist','N/A')} | BB%={ind.get('bb_pct','N/A')}\n"
        f"  حجم={ind.get('vol_ratio','N/A')}x | ATR={ind.get('atr_pct','N/A')}%\n"
        f"  ADX={adx.get('adx','N/A')} — {adx.get('strength','N/A')}\n"
        f"  نظام السوق: {ind.get('regime','N/A')}\n"
        f"{'─'*34}\n"
        f"الدعم والمقاومة\n"
        f"  دعم: {sr.get('nearest_support','N/A')} (بعد {sr.get('dist_to_support','N/A')}%)\n"
        f"  مقاومة: {sr.get('nearest_resistance','N/A')} (بعد {sr.get('dist_to_resistance','N/A')}%)\n"
        f"  {sr.get('context','N/A')}\n"
        f"{'─'*34}\n"
        f"الاطر الزمنية{mtf_text}\n"
        f"{'─'*34}\n"
        f"الانماط الفنية — {pat.get('summary','N/A')}\n"
        f"{patterns_text if patterns_text else '  لا انماط واضحة'}\n"
        f"{'─'*34}\n"
        f"ادارة المخاطر\n"
        f"  VaR(95%): {var_str} | CVaR: {cvar_str}\n"
        f"  الحجم المقترح: {kelly_str} (Kelly)\n"
        f"  مستوى المخاطرة: {risk.get('risk_level','N/A')}\n"
        f"{liquidity_text}\n"
        f"{warnings_text}\n"
        f"{'─'*34}\n"
        f"⏰ {now}"
    )


def format_no_consensus(symbol: str, votes_detail: dict, reason: str) -> str:
    """رسالة داخلية عند عدم الإجماع (لا تُرسل لتيليغرام)"""
    return (
        f"تجاهل {symbol} — {reason}\n"
        f"  BUY:{len(votes_detail.get('BUY',[]))} "
        f"SELL:{len(votes_detail.get('SELL',[]))} "
        f"HOLD:{len(votes_detail.get('HOLD',[]))}"
    )


def send_weekly_report(stats: dict, strategy_update: str) -> bool:
    """إرسال التقرير الأسبوعي"""
    message = (
        f"التقرير الاسبوعي\n"
        f"{'─'*30}\n"
        f"اجمالي الاشارات: {stats.get('total_signals', 0)}\n"
        f"هذا الاسبوع: {stats.get('this_week', 0)}\n"
        f"معدل النجاح: {stats.get('win_rate', 0)}%\n"
        f"{'─'*30}\n"
        f"تحديث الاستراتيجية:\n"
        f"{strategy_update[:500]}\n"
        f"{'─'*30}"
    )
    return send_telegram(message)


def send_startup_message() -> bool:
    """رسالة تأكيد التشغيل"""
    now     = datetime.utcnow().strftime("%H:%M UTC | %Y-%m-%d")
    message = (
        f"🚀 النظام يعمل الآن\n"
        f"⏰ {now}\n"
        f"🔍 جاري مراقبة 17 سوق...\n"
        f"📡 انتظر الإشارات الإجماعية فقط"
    )
    return send_telegram(message)
