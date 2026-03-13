"""
متتبع النتائج — ثلاثة آفاق زمنية
──────────────────────────────────
24h  ← مناسب للتداول اليومي
72h  ← مناسب للسوينج القصير
7d   ← مناسب للسوينج الطويل
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from data.data_layer import UnifiedDataLayer
from notifications.telegram_notifier import send_telegram

HORIZONS = [
    {"col": "outcome_24h", "hours": 24,  "label": "24h"},
    {"col": "outcome_72h", "hours": 72,  "label": "72h"},
    {"col": "outcome_7d",  "hours": 168, "label": "7d" },
]


class OutcomeTracker:

    def __init__(self, db_path: str = "memory/trading_memory.db"):
        self.db_path    = db_path
        self.data_layer = UnifiedDataLayer()

    def _get_price(self, symbol: str):
        try:
            data = self.data_layer.fetch_market_data(symbol, period="5d")
            p    = data.get("price")
            return float(p) if p and p != 0 else None
        except Exception:
            return None

    def _calc(self, price_at: float, price_now: float, direction: str) -> float:
        pct = (price_now - price_at) / price_at * 100
        return round(pct if direction == "BUY" else -pct, 4)

    def update_horizon(self, horizon: dict) -> dict:
        col    = horizon["col"]
        hours  = horizon["hours"]
        label  = horizon["label"]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        conn = sqlite3.connect(self.db_path)
        c    = conn.cursor()
        c.execute(f"""
            SELECT id, symbol, direction, price_at_signal
            FROM signals
            WHERE {col} IS NULL
              AND direction IN ('BUY','SELL')
              AND timestamp <= ?
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()

        updated = wins = losses = 0
        results = []

        for sig_id, symbol, direction, price_at in rows:
            if not price_at or price_at == 0:
                continue
            price_now = self._get_price(symbol)
            if price_now is None:
                continue

            outcome = self._calc(price_at, price_now, direction)

            conn = sqlite3.connect(self.db_path)
            c    = conn.cursor()
            c.execute(f"UPDATE signals SET {col}=?, outcome_checked_at=? WHERE id=?",
                      (outcome, datetime.now(timezone.utc).isoformat(), sig_id))
            if col == "outcome_24h":
                c.execute("UPDATE signals SET outcome_pct=? WHERE id=?", (outcome, sig_id))
            conn.commit()
            conn.close()

            updated += 1
            wins    += outcome > 0
            losses  += outcome <= 0
            results.append({"symbol": symbol, "direction": direction,
                            "outcome": outcome, "horizon": label})
            print(f"   {'✅' if outcome > 0 else '❌'} {symbol} {direction} [{label}]: {outcome:+.2f}%")

        return {"updated": updated, "wins": wins, "losses": losses, "results": results}

    def get_winrates(self) -> dict:
        import pandas as pd
        out = {}
        try:
            conn = sqlite3.connect(self.db_path)
            for h in HORIZONS:
                df = pd.read_sql(
                    f"SELECT {h['col']} as pct FROM signals WHERE {h['col']} IS NOT NULL ORDER BY timestamp DESC LIMIT 100",
                    conn)
                if len(df) >= 5:
                    out[h["label"]] = {"win_rate": round((df["pct"] > 0).mean() * 100, 1), "n": len(df)}
            conn.close()
        except Exception:
            pass
        return out

    def run(self) -> dict:
        print(f"\n{'='*40}")
        print(f"📊 متتبع النتائج — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        print(f"{'='*40}")

        all_results = []
        total_u = total_w = total_l = 0

        for h in HORIZONS:
            print(f"\n⏱️  أفق {h['label']}...")
            r        = self.update_horizon(h)
            total_u += r["updated"]
            total_w += r["wins"]
            total_l += r["losses"]
            all_results += r["results"]

        if all_results:
            self._send_report(all_results, total_w, total_l, self.get_winrates())

        print(f"\n✅ محدَّث: {total_u} | 🏆 {total_w} | ❌ {total_l}")
        return {"updated": total_u, "wins": total_w, "losses": total_l}

    def _send_report(self, results, wins, losses, wr_data):
        total    = wins + losses
        win_rate = (wins / total * 100) if total else 0
        emoji    = "🏆" if win_rate >= 70 else "📊" if win_rate >= 50 else "⚠️"

        details = "\n".join([
            f"   {'✅' if r['outcome']>0 else '❌'} {r['symbol']} {r['direction']} [{r['horizon']}]: `{r['outcome']:+.2f}%`"
            for r in results[:10]
        ])
        wr_text = "".join([f"\n   {lbl}: {d['win_rate']}% ({d['n']} إشارة)" for lbl, d in wr_data.items()])

        send_telegram(f"""
{'─'*30}
{emoji} *تقرير نتائج الإشارات*
{'─'*30}
📈 إجمالي: {total} | ✅ {wins} | ❌ {losses}
🎯 معدل النجاح: *{win_rate:.1f}%*
{'─'*30}
📊 *معدل النجاح لكل أفق:*{wr_text}
{'─'*30}
{details}
{'─'*30}
🧠 _تم تحديث Kelly و Circuit Breaker_""")


if __name__ == "__main__":
    OutcomeTracker().run()
