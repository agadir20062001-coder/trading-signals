"""
نظام الذاكرة والتعلم المستمر
SQLite للتخزين + Reflect Agent أسبوعي
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


class MemorySystem:
    """الذاكرة التراكمية للنظام"""

    def __init__(self, db_path: str = "memory/trading_memory.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    # ============================================================
    # تهيئة قاعدة البيانات
    # ============================================================
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c    = conn.cursor()

        # جدول الإشارات
        c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            asset_type      TEXT,
            direction       TEXT NOT NULL,
            confidence      REAL,
            strength        TEXT,
            votes           TEXT,
            consensus_data  TEXT,
            risk_data       TEXT,
            price_at_signal REAL,
            outcome_pct     REAL,
            outcome_24h     REAL,
            outcome_72h     REAL,
            outcome_7d      REAL,
            outcome_checked_at TEXT,
            notes           TEXT
        )""")

        # ترقية الجدول القديم — إضافة الأعمدة الجديدة إن لم تكن موجودة
        for col in ["outcome_24h", "outcome_72h", "outcome_7d"]:
            try:
                c.execute(f"ALTER TABLE signals ADD COLUMN {col} REAL")
            except Exception:
                pass  # العمود موجود مسبقاً

        # جدول الاستراتيجية المتطورة
        c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_evolution (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL,
            week_number   INTEGER,
            performance_report TEXT,
            updated_prompt TEXT,
            win_rate      REAL,
            total_signals INTEGER
        )""")

        # جدول الإحصاءات اليومية
        c.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date          TEXT PRIMARY KEY,
            signals_sent  INTEGER DEFAULT 0,
            buy_signals   INTEGER DEFAULT 0,
            sell_signals  INTEGER DEFAULT 0,
            hold_signals  INTEGER DEFAULT 0,
            no_consensus  INTEGER DEFAULT 0
        )""")

        conn.commit()
        conn.close()

    # ============================================================
    # حفظ إشارة جديدة
    # ============================================================
    def save_signal(self, symbol: str, consensus: dict,
                    risk: dict, market_data: dict) -> int:
        conn = sqlite3.connect(self.db_path)
        c    = conn.cursor()

        c.execute("""
        INSERT INTO signals
        (timestamp, symbol, asset_type, direction, confidence,
         strength, votes, consensus_data, risk_data, price_at_signal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            symbol,
            market_data.get("type", "unknown"),
            consensus["direction"],
            consensus["avg_confidence"],
            consensus["strength"],
            consensus["votes"],
            json.dumps(consensus, ensure_ascii=False, default=str),
            json.dumps(risk,      ensure_ascii=False, default=str),
            market_data.get("price", 0)
        ))

        signal_id = c.lastrowid

        # تحديث الإحصاءات اليومية
        today = datetime.utcnow().strftime("%Y-%m-%d")
        c.execute("""
        INSERT INTO daily_stats (date, signals_sent)
        VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET
        signals_sent = signals_sent + 1
        """, (today,))

        conn.commit()
        conn.close()
        return signal_id

    # ============================================================
    # فحص الإشارات المكررة — هل أُرسلت إشارة لنفس الرمز مؤخراً؟
    # ============================================================
    def get_recent_signal(self, symbol: str, hours: int = 4) -> dict:
        """
        يتحقق إذا كانت هناك إشارة (BUY أو SELL) لنفس الرمز
        خلال آخر X ساعة — لمنع الإشارات المكررة

        Returns:
            dict مع direction و hours_ago إذا وُجدت
            None إذا لم توجد
        """
        try:
            conn      = sqlite3.connect(self.db_path)
            c         = conn.cursor()
            since     = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

            c.execute("""
                SELECT direction, timestamp
                FROM signals
                WHERE symbol = ?
                  AND direction IN ('BUY', 'SELL')
                  AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol, since))

            row = c.fetchone()
            conn.close()

            if row:
                direction  = row[0]
                ts         = datetime.fromisoformat(row[1])
                hours_ago  = (datetime.utcnow() - ts).total_seconds() / 3600
                return {"direction": direction, "hours_ago": hours_ago}

            return None

        except Exception:
            return None  # في حالة خطأ → اسمح بالإشارة

    # ============================================================
    # تحميل الاستراتيجية الحالية
    # ============================================================
    def load_current_strategy(self) -> str:
        strategy_file = "memory/current_strategy.txt"
        if os.path.exists(strategy_file):
            with open(strategy_file, "r", encoding="utf-8") as f:
                return f.read()

        # الاستراتيجية الافتراضية
        return """
استراتيجية التداول الحالية:
- ركّز على الأصول ذات الزخم القوي
- تجنب الإشارات في أوقات التقلب العالي
- أعطِ أولوية للإشارات المدعومة بحجم تداول مرتفع
- الإجماع الكامل (5/5) أكثر موثوقية من (4/5)
- تحقق من مستوى الدعم والمقاومة قبل الإشارة
"""

    # ============================================================
    # وكيل Reflect + OPRO الأسبوعي
    # ============================================================
    def run_weekly_reflect(self) -> str:
        """
        يشغَّل كل أسبوع — يحلل الأداء ويطور الاستراتيجية
        """
        from agents.voting_agents import get_llm

        conn       = sqlite3.connect(self.db_path)
        week_ago   = (datetime.utcnow() - timedelta(days=7)).isoformat()

        # إشارات الأسبوع
        signals_df = __import__('pandas').read_sql("""
            SELECT symbol, direction, confidence, strength,
                   outcome_pct, timestamp
            FROM signals
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        """, conn, params=(week_ago,))

        # إحصاءات الأداء
        total      = len(signals_df)
        with_outcome = signals_df.dropna(subset=['outcome_pct'])
        wins       = len(with_outcome[with_outcome['outcome_pct'] > 0])
        losses     = len(with_outcome[with_outcome['outcome_pct'] <= 0])
        win_rate   = (wins / len(with_outcome) * 100) if len(with_outcome) > 0 else 0

        conn.close()

        if total == 0:
            return "لا توجد إشارات هذا الأسبوع"

        # الاستراتيجية الحالية
        current_strategy = self.load_current_strategy()

        # استدعاء LLM للتحليل والتطوير
        llm = get_llm()
        response = llm.invoke([{
            "role": "user",
            "content": f"""
أنت وكيل تحليل أداء متخصص في تطوير استراتيجيات التداول.

الإحصاءات الأسبوعية:
- إجمالي الإشارات: {total}
- الإشارات بنتائج: {len(with_outcome)}
- الفائزة: {wins} | الخاسرة: {losses}
- معدل النجاح: {win_rate:.1f}%

الإشارات التفصيلية:
{signals_df.to_string() if not signals_df.empty else "لا بيانات"}

الاستراتيجية الحالية:
{current_strategy}

مهمتك:
1. حلّل أسباب النجاح والفشل
2. اكتشف الأنماط المتكررة
3. اكتب استراتيجية محسّنة للأسبوع القادم

أجب بهذا الشكل:
=== تقرير الأداء ===
[تحليل موجز]

=== الأنماط المكتشفة ===
[ما نجح وما فشل]

=== الاستراتيجية المحدّثة ===
[قواعد واضحة للأسبوع القادم]
"""
        }])

        updated_strategy = response.content

        # حفظ الاستراتيجية الجديدة
        with open("memory/current_strategy.txt", "w", encoding="utf-8") as f:
            f.write(updated_strategy)

        # تسجيل في قاعدة البيانات
        conn = sqlite3.connect(self.db_path)
        c    = conn.cursor()
        week_num = datetime.utcnow().isocalendar()[1]
        c.execute("""
        INSERT INTO strategy_evolution
        (timestamp, week_number, performance_report, updated_prompt, win_rate, total_signals)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            week_num,
            f"نجاح: {win_rate:.1f}%",
            updated_strategy,
            win_rate,
            total
        ))
        conn.commit()
        conn.close()

        return updated_strategy

    # ============================================================
    # إحصاءات سريعة
    # ============================================================
    def get_stats(self) -> dict:
        conn    = sqlite3.connect(self.db_path)
        c       = conn.cursor()
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

        c.execute("SELECT COUNT(*) FROM signals")
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM signals WHERE timestamp > ?", (week_ago,))
        this_week = c.fetchone()[0]

        c.execute("""
        SELECT COUNT(*) FROM signals
        WHERE outcome_pct > 0 AND outcome_pct IS NOT NULL
        """)
        wins = c.fetchone()[0]

        c.execute("""
        SELECT COUNT(*) FROM signals
        WHERE outcome_pct IS NOT NULL
        """)
        with_outcome = c.fetchone()[0]

        conn.close()
        win_rate = (wins / with_outcome * 100) if with_outcome > 0 else 0

        return {
            "total_signals"   : total,
            "this_week"       : this_week,
            "win_rate"        : round(win_rate, 1),
            "signals_with_outcome": with_outcome
        }
