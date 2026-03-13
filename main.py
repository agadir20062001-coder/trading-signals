"""
المنسق الرئيسي — يربط كل المكونات معاً
THE UNIFIED SIGNAL SYSTEM v5
"""

import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# إضافة المسار
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.data_layer         import UnifiedDataLayer
from agents.debate_agents    import run_debate
from risk.risk_engine        import RiskEngine
from memory.memory_system    import MemorySystem
from core.entry_exit         import calculate_entry_exit
from core.market_hours       import filter_open_symbols, is_market_open
from notifications.telegram_notifier import (
    send_telegram,
    format_consensus_signal,
    format_no_consensus,
    send_startup_message,
    send_weekly_report
)
from notifications.email_notifier import send_email_report


class UnifiedSignalSystem:
    """النظام الموحد للإشارات"""

    def __init__(self):
        self.data_layer  = UnifiedDataLayer()
        self.risk_engine = RiskEngine()
        self.memory      = MemorySystem()

        # قراءة الأسواق من .env
        self.watchlist   = self._load_watchlist()

        print("✅ النظام جاهز")
        print(f"📊 الأسواق المراقبة: {len(self.watchlist)} أصل")

    # ============================================================
    # قراءة قائمة المراقبة
    # ============================================================
    def _load_watchlist(self) -> list:
        all_symbols = []

        for key in ["WATCH_STOCKS", "WATCH_CRYPTO",
                    "WATCH_FOREX", "WATCH_COMMODITIES", "WATCH_INDICES"]:
            symbols = os.getenv(key, "")
            if symbols:
                all_symbols.extend([s.strip() for s in symbols.split(",") if s.strip()])

        return all_symbols if all_symbols else ["NVDA", "BTC/USDT", "EURUSD=X"]

    # ============================================================
    # تحليل أصل واحد
    # ============================================================
    def analyze_symbol(self, symbol: str) -> dict:
        print(f"\n{'─'*40}")
        print(f"🔍 تحليل: {symbol}")

        # 1. جلب البيانات
        market_data = self.data_layer.fetch_market_data(symbol)

        if "error" in market_data:
            print(f"   ❌ خطأ في البيانات: {market_data['error']}")
            return {"success": False, "error": market_data["error"]}

        # ── فلتر ما قبل الـLLM ──────────────────────────────────
        # لو السوق عرضي وحجم ضعيف → تخطي النقاش توفيراً للـAPI
        ind       = market_data.get("indicators", {})
        adx_data  = ind.get("adx", {})
        adx_val   = adx_data.get("adx", 0) or 0
        vol_ratio = ind.get("vol_ratio", 1) or 1
        regime    = ind.get("regime", "Normal")

        if adx_val < 15 and vol_ratio < 0.5:
            print(f"   ⏭️ فلتر قبل الـLLM — ADX={adx_val:.1f} + حجم={vol_ratio:.1f}x → سوق خامل")
            return {"success": True, "symbol": symbol, "skipped": True,
                    "reason": "pre_filter"}

        # ── فلتر الإشارات المكررة (4 ساعات) ────────────────────
        recent = self.memory.get_recent_signal(symbol, hours=4)
        if recent:
            print(f"   ⏭️ إشارة مكررة — آخر {recent['direction']} "
                  f"منذ {recent['hours_ago']:.1f} ساعة")
            return {"success": True, "symbol": symbol, "skipped": True,
                    "reason": "duplicate"}

        # 2. بيانات الاقتصاد الكلي
        macro_data = self.data_layer.fetch_macro_data()

        # 3. تعدد الأطر الزمنية
        print(f"   📐 تحليل توافق الأطر الزمنية...")
        dfs = market_data.get("dfs", {})
        mtf = self.data_layer.fetch_multi_timeframe(symbol, dfs=dfs if dfs else None)

        # 4. تحليل السيولة (للكريبتو)
        liquidity = self.data_layer.liquidity_analysis(symbol)

        # 5. النقاش بين الوكلاء
        consensus = run_debate(symbol, market_data, macro_data, mtf)

        # أضف بيانات MTF
        if mtf.get("available"):
            consensus["mtf_alignment"] = mtf.get("alignment", "")
            consensus["mtf_frames"]    = mtf.get("timeframes", {})

        # 6. تأكيد 15M
        if consensus["send_signal"]:
            print(f"   ⏱️ تحقق من تأكيد 15M...")
            conf_15m = self.data_layer.check_15m_confirmation(
                symbol, consensus["direction"]
            )
            delta = conf_15m.get("confidence_delta", 0)
            if delta != 0:
                original = consensus["avg_confidence"]
                consensus["avg_confidence"] = max(0, min(100,
                    consensus["avg_confidence"] + delta
                ))
                print(f"   📐 15M: {conf_15m['label']} "
                      f"({original}% → {consensus['avg_confidence']}%)")
            else:
                print(f"   📐 15M: {conf_15m['label']}")
            consensus["confirmation_15m"] = conf_15m

        # 7. مناطق الدخول والخروج
        entry_exit = {}
        if consensus["send_signal"]:
            entry_exit = calculate_entry_exit(
                direction  = consensus["direction"],
                price      = float(market_data.get("price", 0)),
                indicators = market_data.get("indicators", {}),
            )
            print(f"   🎯 دخول: {entry_exit.get('entry',{}).get('zone','N/A')}")

        # 8. تقييم المخاطر
        risk = self.risk_engine.assess_risk(symbol, market_data)

        # ── Circuit Breaker ──────────────────────────────────────
        if not risk.get("circuit_ok", True):
            consensus["send_signal"] = False
            print(f"   🔴 Circuit Breaker مفعّل — الإشارة موقوفة")

        # 9. القرار
        if consensus["send_signal"]:
            print(f"   ✅ إجماع: {consensus['direction']} {consensus['votes']}")

            self.memory.save_signal(symbol, consensus, risk, market_data)

            # تيليغرام — مكثف وسريع
            message = format_consensus_signal(
                symbol, consensus, risk, market_data, liquidity, entry_exit
            )
            send_telegram(message)
            time.sleep(4)  # منع flood control في تيليغرام

            # إيميل — تقرير مفصل كامل
            send_email_report(
                symbol, consensus, risk, market_data, liquidity, entry_exit
            )

        else:
            direction = consensus.get("direction", "HOLD")
            votes     = consensus.get("votes", "N/A")
            print(f"   ⏭️ لا إشارة — {direction} {votes}")

        return {
            "success"   : True,
            "symbol"    : symbol,
            "consensus" : consensus,
            "risk"      : risk
        }

    # ============================================================
    # تشغيل دورة كاملة على كل الأسواق
    # ============================================================
    def run_cycle(self):
        print(f"\n{'='*40}")
        print(f"🚀 دورة جديدة — {datetime.utcnow().strftime('%H:%M UTC')}")
        print(f"{'='*40}")

        # فلترة الأسواق المفتوحة فقط
        market_filter = filter_open_symbols(self.watchlist)
        print(f"📊 {market_filter['summary']}")

        if not market_filter["any_open"]:
            print("💤 لا توجد أسواق مفتوحة — انتهت الدورة")
            return

        open_symbols = [sym for sym, _ in market_filter["open"]]

        # طباعة المغلقة للمعلومية
        for sym, info in market_filter["closed"]:
            print(f"   ⏭️ تخطي {sym} — {info['reason']}")

        results = []
        for symbol in open_symbols:
            try:
                result = self.analyze_symbol(symbol)
                results.append(result)
                time.sleep(2)
            except Exception as e:
                print(f"   ❌ خطأ في {symbol}: {e}")

        # ملخص الدورة
        signals_sent = sum(
            1 for r in results
            if r.get("success") and r.get("consensus", {}).get("send_signal")
        )
        print(f"\n📊 انتهت الدورة — إشارات أُرسلت: {signals_sent}/{len(self.watchlist)}")

    # ============================================================
    # التقرير الأسبوعي + تطوير الاستراتيجية
    # ============================================================
    def run_weekly_tasks(self):
        print("\n🔄 تشغيل المهام الأسبوعية...")

        # Reflect + OPRO
        strategy_update = self.memory.run_weekly_reflect()

        # إرسال التقرير
        stats = self.memory.get_stats()
        send_weekly_report(stats, strategy_update)

        print("✅ انتهت المهام الأسبوعية")

    # ============================================================
    # التشغيل الرئيسي
    # ============================================================
    def run(self, weekly: bool = False):
        if weekly:
            self.run_weekly_tasks()
        else:
            send_startup_message()
            print("📱 رسالة البدء أُرسلت — انتظار 10 ثوانٍ...")
            import time as _t; _t.sleep(10)  # وقت كافٍ لتيليغرام لتسليمها أولاً
            self.run_cycle()


# ============================================================
# نقطة الدخول
# ============================================================
if __name__ == "__main__":
    UnifiedSignalSystem().run()
