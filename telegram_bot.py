"""
البوت التفاعلي — يجمع بين الأتمتة والتفاعل
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
الوضع 1 — تلقائي (Scheduler داخلي):
  كل 15 دقيقة يحلل الرموز المفتوحة فقط

الوضع 2 — تفاعلي (عند الطلب):
  /analyze NVDA         → تحليل فوري
  /analyze NVDA BTC AAPL → تحليل عدة رموز
  /watchlist            → عرض قائمة المراقبة
  /status               → حالة الأسواق الآن
  /help                 → المساعدة

الوضع 3 — التحديث اليومي:
  كل يوم 08:00 UTC يسأل البوت:
  "هل تريد تعديل قائمة الرموز اليوم؟"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يعمل على: Render.com (مجاني) أو جهازك المحلي
"""

import os
import sys
import json
import time
import threading
import requests
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from main               import UnifiedSignalSystem
from core.market_hours  import filter_open_symbols, is_market_open

# ============================================================
# إعداد البوت
# ============================================================
TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "")
BASE    = f"https://api.telegram.org/bot{TOKEN}"

# ملف حفظ قائمة الرموز المحدثة يومياً
WATCHLIST_FILE = "memory/watchlist_override.json"

# ============================================================
# إرسال رسالة
# ============================================================
def send(text: str, parse_mode: str = "Markdown") -> None:
    try:
        requests.post(
            f"{BASE}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10
        )
    except Exception as e:
        print(f"[تيليغرام] خطأ: {e}")


# ============================================================
# قراءة / حفظ قائمة الرموز
# ============================================================
def load_watchlist() -> list:
    """يقرأ القائمة اليومية إذا وجدت وإلا يرجع للـ .env"""
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE) as f:
                data = json.load(f)
                # إذا القائمة من اليوم → استخدمها
                if data.get("date") == datetime.utcnow().strftime("%Y-%m-%d"):
                    return data.get("symbols", [])
    except:
        pass

    # رجوع للـ .env الافتراضي
    all_symbols = []
    for key in ["WATCH_STOCKS","WATCH_CRYPTO","WATCH_FOREX",
                "WATCH_COMMODITIES","WATCH_INDICES"]:
        raw = os.getenv(key, "")
        if raw:
            all_symbols.extend([s.strip() for s in raw.split(",") if s.strip()])
    return all_symbols or ["NVDA","BTC/USDT","EURUSD=X"]


def save_watchlist(symbols: list) -> None:
    os.makedirs("memory", exist_ok=True)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump({
            "date"   : datetime.utcnow().strftime("%Y-%m-%d"),
            "symbols": symbols
        }, f, ensure_ascii=False)


# ============================================================
# معالجة الأوامر
# ============================================================
def handle_command(text: str, update_id: int) -> None:
    text = text.strip()
    parts = text.split()
    cmd   = parts[0].lower() if parts else ""

    # /help
    if cmd in ["/help", "/start"]:
        send("""
🤖 *أوامر البوت*
━━━━━━━━━━━━━━━━━━━━
`/analyze NVDA` — تحليل رمز واحد فوراً
`/analyze NVDA BTC AAPL` — تحليل عدة رموز
`/watchlist` — عرض قائمة المراقبة الحالية
`/set NVDA BTC AAPL` — تغيير قائمة اليوم
`/status` — حالة الأسواق الآن
`/help` — هذه القائمة
━━━━━━━━━━━━━━━━━━━━
⏱️ التحليل التلقائي يعمل كل 15 دقيقة
   على الأسواق المفتوحة فقط
""")
        return

    # /status
    if cmd == "/status":
        watchlist = load_watchlist()
        result    = filter_open_symbols(watchlist)
        now_utc   = datetime.now(pytz.utc)
        msg = f"⏰ *{now_utc.strftime('%H:%M UTC')}*\n\n"
        msg += f"{result['summary']}\n\n"
        if result["open"]:
            msg += "✅ *مفتوحة:*\n"
            for sym, info in result["open"]:
                msg += f"  • `{sym}` — {info['session']}"
                if info["minutes_left"] < 9999:
                    msg += f" (يغلق بعد {info['minutes_left']} د)"
                msg += "\n"
        if result["closed"]:
            msg += "\n💤 *مغلقة:*\n"
            for sym, info in result["closed"]:
                msg += f"  • `{sym}` — {info['reason']}\n"
                if info.get("next_open"):
                    msg += f"    📅 يفتح: {info['next_open']}\n"
        send(msg)
        return

    # /watchlist
    if cmd == "/watchlist":
        symbols = load_watchlist()
        msg = f"📋 *قائمة المراقبة الحالية ({len(symbols)} رمز)*\n\n"
        for s in symbols:
            info = is_market_open(s)
            icon = "🟢" if info["open"] else "🔴"
            msg += f"  {icon} `{s}`\n"
        msg += "\n_استخدم /set لتغيير القائمة_"
        send(msg)
        return

    # /set NVDA BTC AAPL
    if cmd == "/set":
        new_symbols = [s.upper() for s in parts[1:] if s]
        if not new_symbols:
            send("❌ مثال: `/set NVDA BTC/USDT EURUSD=X`")
            return
        save_watchlist(new_symbols)
        send(f"✅ *قائمة اليوم تم تحديثها:*\n" +
             "\n".join(f"  • `{s}`" for s in new_symbols))
        return

    # /analyze NVDA [BTC AAPL ...]
    if cmd == "/analyze":
        symbols = [s.upper() for s in parts[1:] if s]
        if not symbols:
            send("❌ مثال: `/analyze NVDA` أو `/analyze NVDA BTC AAPL`")
            return

        send(f"⏳ *جاري التحليل...*\n" +
             "\n".join(f"  • `{s}`" for s in symbols))

        system = UnifiedSignalSystem()
        for sym in symbols:
            # تحقق من ساعات السوق
            mh = is_market_open(sym)
            if not mh["open"]:
                send(
                    f"⚠️ *{sym}* — السوق مغلق\n"
                    f"السبب: {mh['reason']}\n"
                    f"📅 يفتح: {mh.get('next_open','قريباً')}\n\n"
                    f"_هل تريد تحليله على أي حال؟ أرسل:_ `/force {sym}`"
                )
                continue
            try:
                system.analyze_symbol(sym)
            except Exception as e:
                send(f"❌ خطأ في تحليل `{sym}`: {str(e)[:100]}")
                notify_error("analyze (تفاعلي)", e, sym)
        return

    # /force NVDA — تحليل إجباري حتى لو السوق مغلق
    if cmd == "/force":
        symbols = [s.upper() for s in parts[1:] if s]
        if not symbols:
            send("❌ مثال: `/force NVDA`")
            return
        send(f"⚡ *تحليل إجباري (السوق قد يكون مغلقاً)*\n" +
             "\n".join(f"  • `{s}`" for s in symbols))
        system = UnifiedSignalSystem()
        for sym in symbols:
            try:
                system.analyze_symbol(sym)
            except Exception as e:
                send(f"❌ خطأ في `{sym}`: {str(e)[:100]}")
        return

    # رد على التحديث اليومي للقائمة
    # المستخدم يرد بأسماء رموز مباشرة (بدون أمر)
    if not cmd.startswith("/") and len(parts) >= 1:
        # تحقق إذا كانت رموز مالية
        likely_symbols = [p.upper() for p in parts
                          if p.replace("/","").replace("=","").replace("^","").isalnum()]
        if likely_symbols and len(likely_symbols) == len(parts):
            save_watchlist(likely_symbols)
            send(f"✅ *قائمة اليوم محدثة بناءً على ردك:*\n" +
                 "\n".join(f"  • `{s}`" for s in likely_symbols))
            return

    send(f"❓ أمر غير معروف: `{text}`\nاكتب /help للمساعدة")


# ============================================================
# الجدولة التلقائية كل 15 دقيقة
# ============================================================
def scheduled_cycle():
    """يعمل كل 15 دقيقة ويحلل الأسواق المفتوحة فقط"""
    try:
        system   = UnifiedSignalSystem()
        watchlist= load_watchlist()
        result   = filter_open_symbols(watchlist)

        if not result["any_open"]:
            print(f"[{datetime.utcnow().strftime('%H:%M UTC')}] 💤 كل الأسواق مغلقة — تخطي")
            return

        open_symbols = [sym for sym, _ in result["open"]]
        print(f"[{datetime.utcnow().strftime('%H:%M UTC')}] "
              f"🔍 تحليل {len(open_symbols)}/{len(watchlist)} رمز مفتوح")

        failed = []
        for sym in open_symbols:
            try:
                system.analyze_symbol(sym)
                time.sleep(2)
            except Exception as e:
                failed.append(sym)
                print(f"  ❌ خطأ في {sym}: {e}")
                notify_error("scheduled_cycle", e, sym)

        # ملخص إذا كان هناك فشل جزئي
        if failed and len(failed) < len(open_symbols):
            send(f"⚠️ *الدورة انتهت مع {len(failed)} خطأ*\n"
                 f"فشل: {', '.join(f'`{s}`' for s in failed)}")

    except Exception as e:
        notify_error("scheduled_cycle — خطأ عام", e)


# ============================================================
# التحديث اليومي للقائمة — 08:00 UTC
# ============================================================
def daily_watchlist_prompt():
    """يسأل المستخدم كل يوم عن رموز اليوم"""
    current = load_watchlist()
    current_str = " | ".join(f"`{s}`" for s in current)
    send(f"""
📅 *صباح الخير! قائمة اليوم*
━━━━━━━━━━━━━━━━━━━━
القائمة الحالية:
{current_str}

هل تريد تعديلها؟
• أرسل الرموز مباشرة: `NVDA BTC/USDT AAPL`
• أو أرسل /set مع الرموز الجديدة
• أو تجاهل هذه الرسالة للإبقاء على القائمة الحالية
━━━━━━━━━━━━━━━━━━━━
_التحليل التلقائي سيبدأ بعد 15 دقيقة_
""")


# ============================================================
# خيط الجدولة (Scheduler Thread)
# ============================================================
def scheduler_thread():
    """
    خيط مستقل يراقب الوقت ويطلق:
    - كل 15 دقيقة → تحليل
    - كل يوم 08:00 UTC → سؤال القائمة اليومية
    """
    last_cycle  = 0
    last_prompt = ""

    print("⏱️ [Scheduler] يعمل...")

    while True:
        now     = datetime.now(pytz.utc)
        now_ts  = time.time()
        today   = now.strftime("%Y-%m-%d")

        # كل 15 دقيقة
        if now_ts - last_cycle >= 900:
            scheduled_cycle()
            last_cycle = now_ts

        # كل يوم 08:00 UTC
        if now.hour == 8 and now.minute < 15 and last_prompt != today:
            daily_watchlist_prompt()
            last_prompt = today

        time.sleep(60)   # فحص كل دقيقة


# ============================================================
# إشعار الفشل — يُرسل عند أي خطأ حرج
# ============================================================
def notify_error(context: str, error: Exception, symbol: str = None) -> None:
    """يرسل تنبيه فوري على تيليغرام عند الفشل"""
    sym_text = f" | الرمز: `{symbol}`" if symbol else ""
    send(
        f"⚠️ *تنبيه خطأ*{sym_text}\n"
        f"📍 المكان: `{context}`\n"
        f"❌ الخطأ: `{str(error)[:150]}`\n"
        f"⏰ {datetime.now(pytz.utc).strftime('%H:%M UTC')}"
    )


# ============================================================
# استقبال الرسائل (Polling)
# ============================================================
def polling_loop():
    """يستقبل رسائل تيليغرام باستمرار"""
    offset = None
    print("📡 [Bot] يستمع للرسائل...")

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset

            r = requests.get(f"{BASE}/getUpdates", params=params, timeout=35)
            data = r.json()

            for update in data.get("result", []):
                offset = update["id"] + 1
                msg    = update.get("message", {})
                text   = msg.get("text", "").strip()
                chat   = str(msg.get("chat", {}).get("id", ""))

                # تجاهل الرسائل من غير الـ chat_id المصرح به
                if chat != CHAT_ID:
                    continue

                if text:
                    print(f"[Bot] رسالة: {text}")
                    try:
                        handle_command(text, update["id"])
                    except Exception as e:
                        send(f"❌ خطأ داخلي: {str(e)[:100]}")
                        notify_error("handle_command", e)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"[Bot] خطأ في الاستقبال: {e}")
            notify_error("polling_loop", e)
            time.sleep(5)


# ============================================================
# نقطة الدخول
# ============================================================
if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير موجودة في .env")
        sys.exit(1)

    send("🚀 *البوت يعمل الآن*\n"
         "⏱️ التحليل التلقائي كل 15 دقيقة\n"
         "💬 اكتب /help للأوامر المتاحة")

    # خيط الجدولة في الخلفية
    t = threading.Thread(target=scheduler_thread, daemon=True)
    t.start()

    # حلقة استقبال الرسائل (الخيط الرئيسي)
    polling_loop()
