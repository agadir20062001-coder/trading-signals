"""
محرك المخاطر — مستوحى من CloddsBot
VaR + CVaR + Kelly Sizing + Volatility Regime + Circuit Breaker
"""

import numpy as np
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


class RiskEngine:
    """محرك المخاطر الشامل"""

    def __init__(self, db_path: str = "memory/trading_memory.db"):
        self.db_path          = db_path
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "5.0"))
        self.circuit_broken   = self._check_circuit()  # يتحقق فعلياً عند البدء

    # ============================================================
    # Circuit Breaker الحقيقي — يحسب PnL اليوم من السجل
    # ============================================================
    def _check_circuit(self) -> bool:
        """
        يحسب إجمالي خسائر اليوم من جدول signals
        لو تجاوزت الحد → يوقف الإرسال لبقية اليوم
        """
        try:
            conn  = sqlite3.connect(self.db_path)
            today = datetime.now().strftime("%Y-%m-%d")
            df    = pd.read_sql(
                """SELECT outcome_pct FROM signals
                   WHERE DATE(timestamp) = ?
                     AND outcome_pct IS NOT NULL""",
                conn, params=(today,)
            )
            conn.close()

            if df.empty:
                return False  # لا بيانات = لا قطع

            daily_pnl = df["outcome_pct"].sum()

            if daily_pnl <= -self.daily_loss_limit:
                print(f"   🔴 Circuit Breaker: خسارة اليوم={daily_pnl:.1f}% ≥ حد={self.daily_loss_limit}%")
                return True

            return False

        except Exception:
            return False  # في حالة خطأ → لا تقطع

    # ============================================================
    # VaR و CVaR — قياس الخسارة المحتملة
    # ============================================================
    def calculate_var_cvar(self, df: pd.DataFrame, confidence: float = 0.95) -> dict:
        """
        VaR: ما أقصى خسارة بثقة 95%؟
        CVaR: إذا تجاوزنا VaR — كم سنخسر؟
        """
        if df is None or df.empty or len(df) < 20:
            return {"var": None, "cvar": None, "available": False}

        returns = df['close'].pct_change().dropna() * 100

        var  = float(np.percentile(returns, (1 - confidence) * 100))
        cvar = float(returns[returns <= var].mean())

        return {
            "available"  : True,
            "var"        : round(abs(var), 2),
            "cvar"       : round(abs(cvar), 2),
            "confidence" : int(confidence * 100)
        }

    # ============================================================
    # Kelly Sizing — الحجم الأمثل للمركز
    # ============================================================
    def kelly_sizing(self, win_rate: float, avg_win: float, avg_loss: float) -> dict:
        """
        صيغة Kelly: f = (p*b - q) / b
        نستخدم نصف Kelly للأمان
        """
        if avg_loss == 0:
            return {"full_kelly": 0, "half_kelly": 0, "recommended": 0}

        b           = avg_win / avg_loss
        q           = 1 - win_rate
        full_kelly  = (win_rate * b - q) / b
        half_kelly  = full_kelly / 2

        full_kelly  = max(0, min(full_kelly, 1))
        half_kelly  = max(0, min(half_kelly, 0.25))

        return {
            "full_kelly" : round(full_kelly * 100, 1),
            "half_kelly" : round(half_kelly * 100, 1),
            "recommended": round(half_kelly * 100, 1)
        }

    # ============================================================
    # تقييم المخاطر الكامل لأصل معين
    # ============================================================
    def assess_risk(self, symbol: str, market_data: dict) -> dict:
        df  = market_data.get("df")
        ind = market_data.get("indicators", {})

        # VaR و CVaR
        var_data = self.calculate_var_cvar(df)

        # حساب Kelly من السجل التاريخي
        kelly_data = self._get_historical_kelly(symbol)

        # نظام التقلب
        regime = ind.get("regime", "Normal Volatility")

        # فلتر الخطورة
        risk_score   = 0
        risk_warnings = []

        rsi = ind.get("rsi", 50)
        if rsi > 80:
            risk_score += 2
            risk_warnings.append("RSI في منطقة تشبع شراء شديد")
        elif rsi > 70:
            risk_score += 1
            risk_warnings.append("RSI في منطقة تشبع شراء")
        elif rsi < 20:
            risk_score += 2
            risk_warnings.append("RSI في منطقة تشبع بيع شديد")

        if regime == "High Volatility":
            risk_score += 2
            risk_warnings.append("تقلب مرتفع — حجم أصغر موصى به")
        elif regime == "Low Volatility":
            risk_warnings.append("تقلب منخفض — تحرك محتمل قادم")

        vol_ratio = ind.get("vol_ratio", 1)
        if vol_ratio > 3:
            risk_score += 1
            risk_warnings.append(f"حجم تداول غير عادي ({vol_ratio}x)")

        # تحديد مستوى المخاطرة
        if risk_score >= 4:
            risk_level = "عالية جداً 🔴"
        elif risk_score >= 2:
            risk_level = "متوسطة 🟡"
        else:
            risk_level = "منخفضة 🟢"

        return {
            "symbol"      : symbol,
            "var"         : var_data,
            "kelly"       : kelly_data,
            "regime"      : regime,
            "risk_score"  : risk_score,
            "risk_level"  : risk_level,
            "warnings"    : risk_warnings,
            "circuit_ok"  : not self.circuit_broken
        }

    # ============================================================
    # حساب Kelly من السجل التاريخي
    # ============================================================
    def _get_historical_kelly(self, symbol: str) -> dict:
        try:
            conn = sqlite3.connect(self.db_path)
            df   = pd.read_sql(
                """SELECT outcome_pct FROM signals
                   WHERE symbol=? AND outcome_pct IS NOT NULL
                   ORDER BY timestamp DESC LIMIT 50""",
                conn, params=(symbol,)
            )
            conn.close()

            if len(df) < 10:
                return {"recommended": 15, "note": "بيانات غير كافية — افتراضي 15%"}

            wins    = df[df['outcome_pct'] > 0]['outcome_pct']
            losses  = df[df['outcome_pct'] < 0]['outcome_pct'].abs()
            win_rate = len(wins) / len(df)
            avg_win  = wins.mean()  if len(wins)   > 0 else 1
            avg_loss = losses.mean() if len(losses) > 0 else 1

            return self.kelly_sizing(win_rate, avg_win, avg_loss)

        except:
            return {"recommended": 15, "note": "افتراضي 15%"}
