"""
طبقة البيانات الموحدة — كل الأسواق في مكان واحد
أسهم + كريبتو + فوركس + سلع + مؤشرات
"""

import ccxt
import yfinance as yf
import pandas as pd
import numpy as np
import pandas_ta as ta
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


class UnifiedDataLayer:
    """طبقة بيانات موحدة لجميع الأسواق"""

    def __init__(self):
        # منصة كريبتو افتراضية
        self.crypto_exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.fred_api_key = os.getenv("FRED_API_KEY", "")

    # ============================================================
    # تحديد نوع الأصل تلقائياً
    # ============================================================
    def detect_asset_type(self, symbol: str) -> str:
        if "/" in symbol and "USDT" in symbol.upper():
            return "crypto"
        elif "=X" in symbol:
            return "forex"
        elif "=F" in symbol:
            return "commodity"
        elif symbol.startswith("^"):
            return "index"
        else:
            return "stock"

    # ============================================================
    # جلب البيانات بناءً على نوع الأصل
    # ============================================================
    def fetch_market_data(self, symbol: str, period: str = "90d") -> dict:
        asset_type = self.detect_asset_type(symbol)

        try:
            if asset_type == "crypto":
                return self._fetch_crypto(symbol)
            else:
                return self._fetch_yfinance(symbol, period, asset_type)
        except Exception as e:
            return {"error": str(e), "symbol": symbol, "type": asset_type}

    # ============================================================
    # بيانات الكريبتو عبر ccxt — 3 أطر زمنية
    # ============================================================
    def _fetch_crypto(self, symbol: str) -> dict:
        # --- جلب الأطر الثلاثة ---
        dfs = {}
        for tf, label, limit in [("1h","1H",200), ("4h","4H",150), ("1d","1D",200)]:
            try:
                ohlcv = self.crypto_exchange.fetch_ohlcv(
                    symbol, timeframe=tf, limit=limit
                )
                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp','open','high','low','close','volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                dfs[label] = df
            except:
                dfs[label] = pd.DataFrame()

        # دفتر الأوامر للسيولة
        try:
            orderbook = self.crypto_exchange.fetch_order_book(symbol, limit=20)
            bid_liq   = sum(b[1] for b in orderbook['bids'])
            ask_liq   = sum(a[1] for a in orderbook['asks'])
            liq_ratio = round(bid_liq / ask_liq, 3) if ask_liq else 1
        except:
            liq_ratio = 1

        indicators = self._calculate_indicators_mtf(dfs)
        ticker     = self.crypto_exchange.fetch_ticker(symbol)

        return {
            "symbol"         : symbol,
            "type"           : "crypto",
            "price"          : ticker['last'],
            "change_24h"     : ticker.get('percentage', 0),
            "volume_24h"     : ticker.get('quoteVolume', 0),
            "liquidity_ratio": liq_ratio,
            "indicators"     : indicators,
            "df"             : dfs.get("1H", pd.DataFrame()),
            "dfs"            : dfs
        }

    # ============================================================
    # بيانات الأسهم والفوركس والسلع — 3 أطر زمنية
    # ============================================================
    def _fetch_yfinance(self, symbol: str, period: str, asset_type: str) -> dict:
        ticker = yf.Ticker(symbol)
        dfs    = {}

        # 1H — آخر 60 يوماً (حد yfinance)
        try:
            df1h = ticker.history(period="60d", interval="1h")
            df1h.columns = [c.lower() for c in df1h.columns]
            dfs["1H"] = df1h if not df1h.empty else pd.DataFrame()
        except:
            dfs["1H"] = pd.DataFrame()

        # 4H — نبنيه من 1H بأخذ كل 4 شموع
        try:
            if not dfs["1H"].empty:
                df4h = dfs["1H"].resample("4h").agg({
                    'open' : 'first', 'high': 'max',
                    'low'  : 'min',   'close':'last',
                    'volume':'sum'
                }).dropna()
                dfs["4H"] = df4h
            else:
                dfs["4H"] = pd.DataFrame()
        except:
            dfs["4H"] = pd.DataFrame()

        # 1D — آخر سنة
        try:
            df1d = ticker.history(period="1y", interval="1d")
            df1d.columns = [c.lower() for c in df1d.columns]
            dfs["1D"] = df1d if not df1d.empty else pd.DataFrame()
        except:
            dfs["1D"] = pd.DataFrame()

        indicators = self._calculate_indicators_mtf(dfs)

        # السعر من آخر إطار متاح
        _h1 = dfs.get("1H", pd.DataFrame())
        _d1 = dfs.get("1D", pd.DataFrame())
        df_main = _h1 if (_h1 is not None and not _h1.empty) else \
                  (_d1 if (_d1 is not None and not _d1.empty) else pd.DataFrame())
        price      = float(df_main['close'].iloc[-1]) if not df_main.empty else 0
        prev_close = float(df_main['close'].iloc[-2]) if len(df_main) > 1 else price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

        info = ticker.info or {}
        return {
            "symbol"     : symbol,
            "type"       : asset_type,
            "price"      : round(price, 4),
            "change_24h" : round(change_pct, 2),
            "volume"     : float(df_main['volume'].iloc[-1]) if 'volume' in df_main else 0,
            "market_cap" : info.get('marketCap', 'N/A'),
            "pe_ratio"   : info.get('trailingPE', 'N/A'),
            "eps"        : info.get('trailingEps', 'N/A'),
            "sector"     : info.get('sector', 'N/A'),
            "indicators" : indicators,
            "df"         : df_main,
            "dfs"        : dfs
        }

    # ============================================================
    # المنسق الرئيسي — يوزع كل مؤشر على إطاره الصحيح
    # ============================================================
    def _calculate_indicators_mtf(self, dfs: dict) -> dict:
        """
        التوزيع الصحيح للأطر الزمنية:
        ┌─────────────────────────────────────────────┐
        │  1H → RSI, MACD, BB, MA, ATR, حجم, تقلب    │
        │  4H → ADX, Stochastic, شموع يابانية        │
        │  1D → دعم/مقاومة, أنماط مخططية (HH/HL...) │
        └─────────────────────────────────────────────┘
        """
        df_1h = dfs.get("1H", pd.DataFrame())
        df_4h = dfs.get("4H", pd.DataFrame())
        df_1d = dfs.get("1D", pd.DataFrame())

        result = {}

        # --- 1H: المؤشرات السريعة ---
        if not df_1h.empty and len(df_1h) >= 20:
            result.update(self._indicators_1h(df_1h))
            result["timeframe_1h"] = "✅"
        else:
            result["timeframe_1h"] = "❌"

        # --- 4H: ADX + Stochastic + شموع ---
        if not df_4h.empty and len(df_4h) >= 14:
            result["adx"]      = self._calculate_adx(df_4h['high'], df_4h['low'], df_4h['close'])
            result["stoch"]    = self._calculate_stochastic(df_4h['high'], df_4h['low'], df_4h['close'])
            result["candles"]  = self._detect_candle_patterns(df_4h)
            result["timeframe_4h"] = "✅"
        elif not df_1h.empty and len(df_1h) >= 14:
            # احتياط: استخدم 1H إذا لم يتوفر 4H
            result["adx"]      = self._calculate_adx(df_1h['high'], df_1h['low'], df_1h['close'])
            result["stoch"]    = self._calculate_stochastic(df_1h['high'], df_1h['low'], df_1h['close'])
            result["candles"]  = self._detect_candle_patterns(df_1h)
            result["timeframe_4h"] = "⚠️ (1H)"
        else:
            result["adx"]      = {"adx": None, "strength": "غير متاح", "tradeable": True}
            result["stoch"]    = {"k": None, "d": None, "signal": "غير متاح"}
            result["candles"]  = {"detected": [], "bias": 0, "summary": "غير متاح"}
            result["timeframe_4h"] = "❌"

        # --- 1D: دعم/مقاومة + أنماط مخططية ---
        if not df_1d.empty and len(df_1d) >= 20:
            result["sr"]       = self._calculate_support_resistance(df_1d['high'], df_1d['low'], df_1d['close'])
            result["chart"]    = self._detect_chart_patterns(df_1d)
            result["timeframe_1d"] = "✅"
        elif not df_1h.empty:
            result["sr"]       = self._calculate_support_resistance(df_1h['high'], df_1h['low'], df_1h['close'])
            result["chart"]    = self._detect_chart_patterns(df_1h)
            result["timeframe_1d"] = "⚠️ (1H)"
        else:
            result["sr"]       = {"nearest_support": None, "nearest_resistance": None, "context": "غير متاح"}
            result["chart"]    = {"detected": [], "bias": 0, "summary": "غير متاح"}
            result["timeframe_1d"] = "❌"

        # --- دمج الأنماط الكاملة للعرض ---
        all_detected = (
            result.get("candles", {}).get("detected", []) +
            result.get("chart",   {}).get("detected", [])
        )
        total_bias = (
            result.get("candles", {}).get("bias", 0) +
            result.get("chart",   {}).get("bias", 0)
        )
        if total_bias >= 3:
            pat_summary = "إشارات صعودية قوية 🟢🟢"
        elif total_bias >= 1:
            pat_summary = "ميل صعودي 🟢"
        elif total_bias <= -3:
            pat_summary = "إشارات هبوطية قوية 🔴🔴"
        elif total_bias <= -1:
            pat_summary = "ميل هبوطي 🔴"
        else:
            pat_summary = "محايد ⚖️"

        result["patterns"] = {
            "detected": all_detected,
            "bias"    : total_bias,
            "summary" : pat_summary,
            "count"   : len(all_detected)
        }

        return result

    # ============================================================
    # 1H — RSI, MACD, Bollinger, MA, ATR, حجم, تقلب
    # ============================================================
    def _indicators_1h(self, df: pd.DataFrame) -> dict:
        close  = df['close']
        high   = df['high']
        low    = df['low']
        volume = df.get('volume', pd.Series([0]*len(df), index=df.index))
        price  = float(close.iloc[-1])

        # المتوسطات المتحركة
        ma20  = float(close.rolling(20).mean().iloc[-1])
        ma50  = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # RSI (14)
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - (100 / (1 + rs))).iloc[-1])

        # MACD (12/26/9)
        ema12      = close.ewm(span=12).mean()
        ema26      = close.ewm(span=26).mean()
        macd_line  = ema12 - ema26
        macd_sig   = macd_line.ewm(span=9).mean()
        macd_hist  = float((macd_line - macd_sig).iloc[-1])
        macd_val   = float(macd_line.iloc[-1])
        macd_sval  = float(macd_sig.iloc[-1])

        # Bollinger Bands (20, 2σ)
        sma20  = close.rolling(20).mean()
        std20  = close.rolling(20).std()
        bb_up  = float((sma20 + 2*std20).iloc[-1])
        bb_low = float((sma20 - 2*std20).iloc[-1])
        bb_mid = float(sma20.iloc[-1])
        bb_pct = (price - bb_low) / (bb_up - bb_low) if (bb_up - bb_low) else 0.5

        # ATR (14)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr     = float(tr.rolling(14).mean().iloc[-1])
        atr_pct = (atr / price * 100) if price else 0

        # حجم التداول النسبي
        vol_avg   = volume.rolling(20).mean().iloc[-1]
        vol_ratio = float(volume.iloc[-1] / vol_avg) if vol_avg else 1

        # نظام التقلب
        hist_vol = float(close.pct_change().rolling(20).std().iloc[-1] * 100)
        if hist_vol < 1.0:
            regime = "Low Volatility"
        elif hist_vol < 2.5:
            regime = "Normal Volatility"
        else:
            regime = "High Volatility"

        return {
            "price"      : round(price, 4),
            "ma20"       : round(ma20, 4),
            "ma50"       : round(ma50, 4),
            "ma200"      : round(ma200, 4) if ma200 else None,
            "rsi"        : round(rsi, 2),
            "macd"       : round(macd_val, 4),
            "macd_signal": round(macd_sval, 4),
            "macd_hist"  : round(macd_hist, 4),
            "bb_upper"   : round(bb_up, 4),
            "bb_lower"   : round(bb_low, 4),
            "bb_mid"     : round(bb_mid, 4),
            "bb_pct"     : round(bb_pct, 3),
            "atr_pct"    : round(atr_pct, 3),
            "vol_ratio"  : round(vol_ratio, 2),
            "regime"     : regime,
            "hist_vol"   : round(hist_vol, 3),
        }

    # ============================================================
    # 4H — Stochastic Oscillator
    # ============================================================
    def _calculate_stochastic(self, high: pd.Series, low: pd.Series,
                               close: pd.Series, k_period: int = 14,
                               d_period: int = 3) -> dict:
        try:
            lowest_low   = low.rolling(k_period).min()
            highest_high = high.rolling(k_period).max()
            k = ((close - lowest_low) / (highest_high - lowest_low) * 100)
            d = k.rolling(d_period).mean()

            k_val = float(k.iloc[-1])
            d_val = float(d.iloc[-1])

            if k_val > 80:
                sig = "تشبع شراء ⚠️"
            elif k_val < 20:
                sig = "تشبع بيع ⚠️"
            elif k_val > d_val:
                sig = "صعودي 📈"
            else:
                sig = "هبوطي 📉"

            return {
                "k"     : round(k_val, 2),
                "d"     : round(d_val, 2),
                "signal": sig
            }
        except:
            return {"k": None, "d": None, "signal": "غير متاح"}

    # ============================================================
    # 4H — الشموع اليابانية
    # ============================================================
    def _detect_candle_patterns(self, df: pd.DataFrame) -> dict:
        try:
            o = df['open']  if 'open'  in df.columns else df['close'].shift(1)
            c = df['close']
            h = df['high']
            l = df['low']

            detected = []
            bias     = 0

            body   = (c - o).abs()
            candle = h - l

            # Doji — تردد
            if float(candle.iloc[-1]) > 0:
                if float(body.iloc[-1]) / float(candle.iloc[-1]) < 0.1:
                    detected.append("Doji ⚖️ [4H] (تردد)")

            # Bullish Engulfing — ابتلاع صعودي
            if len(c) >= 2:
                pb = float(c.iloc[-2]) < float(o.iloc[-2])
                cb = float(c.iloc[-1]) > float(o.iloc[-1])
                eg = (float(c.iloc[-1]) > float(o.iloc[-2]) and
                      float(o.iloc[-1]) < float(c.iloc[-2]))
                if pb and cb and eg:
                    detected.append("Bullish Engulfing 🟢 [4H] (+)")
                    bias += 2

            # Bearish Engulfing — ابتلاع هبوطي
            if len(c) >= 2:
                pb2 = float(c.iloc[-2]) > float(o.iloc[-2])
                cb2 = float(c.iloc[-1]) < float(o.iloc[-1])
                eg2 = (float(c.iloc[-1]) < float(o.iloc[-2]) and
                       float(o.iloc[-1]) > float(c.iloc[-2]))
                if pb2 and cb2 and eg2:
                    detected.append("Bearish Engulfing 🔴 [4H] (-)")
                    bias -= 2

            # Hammer — مطرقة
            lw = float(c.iloc[-1]) - float(l.iloc[-1])
            uw = float(h.iloc[-1]) - float(c.iloc[-1])
            bs = float(body.iloc[-1])
            if bs > 0 and lw > 2 * bs and uw < bs:
                detected.append("Hammer 🔨 [4H] (قاع محتمل +)")
                bias += 1

            # Inverted Hammer — مطرقة مقلوبة
            if bs > 0 and uw > 2 * bs and lw < bs:
                if float(c.iloc[-1]) > float(o.iloc[-2]):  # في اتجاه صعودي
                    detected.append("Inverted Hammer 🔨↑ [4H] (+)")
                    bias += 1

            # Shooting Star — نجمة ساقطة
            if bs > 0 and uw > 2 * bs and lw < bs:
                if float(c.iloc[-1]) < float(o.iloc[-2]):  # في اتجاه هبوطي
                    detected.append("Shooting Star ⭐ [4H] (قمة محتملة -)")
                    bias -= 1

            # Hanging Man — رجل معلق
            if len(c) >= 3:
                uptrend = float(c.iloc[-3]) < float(c.iloc[-2]) < float(h.iloc[-1])
                if uptrend and lw > 2 * bs and uw < bs:
                    detected.append("Hanging Man 🪢 [4H] (تحذير هبوط -)")
                    bias -= 1

            # Bullish Harami — حرامي صعودي
            if len(c) >= 2:
                big_bear  = float(o.iloc[-2]) > float(c.iloc[-2])
                small_bull= float(c.iloc[-1]) > float(o.iloc[-1])
                inside    = (float(c.iloc[-1]) < float(o.iloc[-2]) and
                             float(o.iloc[-1]) > float(c.iloc[-2]))
                if big_bear and small_bull and inside:
                    detected.append("Bullish Harami 🟢 [4H] (+)")
                    bias += 1

            # Bearish Harami — حرامي هبوطي
            if len(c) >= 2:
                big_bull  = float(c.iloc[-2]) > float(o.iloc[-2])
                small_bear= float(c.iloc[-1]) < float(o.iloc[-1])
                inside2   = (float(c.iloc[-1]) > float(o.iloc[-2]) and
                             float(o.iloc[-1]) < float(c.iloc[-2]))
                if big_bull and small_bear and inside2:
                    detected.append("Bearish Harami 🔴 [4H] (-)")
                    bias -= 1

            # Three White Soldiers — ثلاثة جنود بيض
            if len(c) >= 3:
                s1 = float(c.iloc[-3]) > float(o.iloc[-3])
                s2 = float(c.iloc[-2]) > float(o.iloc[-2])
                s3 = float(c.iloc[-1]) > float(o.iloc[-1])
                a1 = float(c.iloc[-2]) > float(c.iloc[-3])
                a2 = float(c.iloc[-1]) > float(c.iloc[-2])
                if s1 and s2 and s3 and a1 and a2:
                    detected.append("Three White Soldiers ✅✅✅ [4H] (صعود قوي +)")
                    bias += 3

            # Three Black Crows — ثلاثة غربان سوداء
            if len(c) >= 3:
                b1 = float(c.iloc[-3]) < float(o.iloc[-3])
                b2 = float(c.iloc[-2]) < float(o.iloc[-2])
                b3 = float(c.iloc[-1]) < float(o.iloc[-1])
                d1 = float(c.iloc[-2]) < float(c.iloc[-3])
                d2 = float(c.iloc[-1]) < float(c.iloc[-2])
                if b1 and b2 and b3 and d1 and d2:
                    detected.append("Three Black Crows ❌❌❌ [4H] (هبوط قوي -)")
                    bias -= 3

            # Morning Star — نجمة الصباح
            if len(c) >= 3:
                big_bear3  = float(c.iloc[-3]) < float(o.iloc[-3])
                small_body = float(body.iloc[-2]) < float(body.iloc[-3]) * 0.3
                bull_close = float(c.iloc[-1]) > float(o.iloc[-1])
                recovery   = float(c.iloc[-1]) > (float(o.iloc[-3]) + float(c.iloc[-3])) / 2
                if big_bear3 and small_body and bull_close and recovery:
                    detected.append("Morning Star 🌅 [4H] (انعكاس صعودي +)")
                    bias += 3

            # Evening Star — نجمة المساء
            if len(c) >= 3:
                big_bull3  = float(c.iloc[-3]) > float(o.iloc[-3])
                small_body2= float(body.iloc[-2]) < float(body.iloc[-3]) * 0.3
                bear_close = float(c.iloc[-1]) < float(o.iloc[-1])
                reversal   = float(c.iloc[-1]) < (float(o.iloc[-3]) + float(c.iloc[-3])) / 2
                if big_bull3 and small_body2 and bear_close and reversal:
                    detected.append("Evening Star 🌆 [4H] (انعكاس هبوطي -)")
                    bias -= 3

            # Marubozu صعودي — شمعة قوية بدون ظلال
            if bs > 0:
                uw_ratio = uw / float(candle.iloc[-1]) if float(candle.iloc[-1]) else 1
                lw_ratio = lw / float(candle.iloc[-1]) if float(candle.iloc[-1]) else 1
                bull_bar = float(c.iloc[-1]) > float(o.iloc[-1])
                if bull_bar and uw_ratio < 0.05 and lw_ratio < 0.05:
                    detected.append("Bullish Marubozu 🟩 [4H] (زخم صعودي +)")
                    bias += 2
                elif not bull_bar and uw_ratio < 0.05 and lw_ratio < 0.05:
                    detected.append("Bearish Marubozu 🟥 [4H] (زخم هبوطي -)")
                    bias -= 2

            summary = (
                "إشارات شمعية صعودية قوية 🟢🟢" if bias >= 3 else
                "ميل شمعي صعودي 🟢"              if bias >= 1 else
                "إشارات شمعية هبوطية قوية 🔴🔴"  if bias <= -3 else
                "ميل شمعي هبوطي 🔴"               if bias <= -1 else
                "شموع محايدة ⚖️"
            )

            return {"detected": detected, "bias": bias, "summary": summary,
                    "count": len(detected), "timeframe": "4H"}

        except Exception as e:
            return {"detected": [], "bias": 0, "summary": "غير متاح",
                    "count": 0, "timeframe": "4H"}

    # ============================================================
    # 1D — الأنماط المخططية (Chart Patterns)
    # ============================================================
    def _detect_chart_patterns(self, df: pd.DataFrame) -> dict:
        try:
            close = df['close']
            high  = df['high']
            low   = df['low']
            h     = high.iloc[-100:] if len(high) >= 100 else high
            l     = low.iloc[-100:]  if len(low)  >= 100 else low
            c     = close.iloc[-100:]if len(close) >= 100 else close

            detected = []
            bias     = 0

            # Higher Highs + Higher Lows — اتجاه صعودي
            if len(h) >= 10:
                hh = float(h.iloc[-1]) > float(h.iloc[-5]) > float(h.iloc[-10])
                hl = float(l.iloc[-1]) > float(l.iloc[-5]) > float(l.iloc[-10])
                if hh and hl:
                    detected.append("Higher Highs/Lows 📈 [1D] (اتجاه صعودي +)")
                    bias += 2

            # Lower Highs + Lower Lows — اتجاه هبوطي
            if len(h) >= 10:
                lh = float(h.iloc[-1]) < float(h.iloc[-5]) < float(h.iloc[-10])
                ll = float(l.iloc[-1]) < float(l.iloc[-5]) < float(l.iloc[-10])
                if lh and ll:
                    detected.append("Lower Highs/Lows 📉 [1D] (اتجاه هبوطي -)")
                    bias -= 2

            # Double Bottom — قاع مزدوج
            if len(l) >= 20:
                rl  = l.rolling(5).min()
                l1  = float(rl.iloc[-10])
                l2  = float(rl.iloc[-1])
                if l1 > 0 and abs(l1 - l2) / l1 < 0.02 and float(c.iloc[-1]) > float(c.iloc[-10]):
                    detected.append("Double Bottom 🔔 [1D] (انعكاس صعودي +)")
                    bias += 2

            # Double Top — قمة مزدوجة
            if len(h) >= 20:
                rh  = h.rolling(5).max()
                h1  = float(rh.iloc[-10])
                h2  = float(rh.iloc[-1])
                if h1 > 0 and abs(h1 - h2) / h1 < 0.02 and float(c.iloc[-1]) < float(c.iloc[-10]):
                    detected.append("Double Top 🔔 [1D] (انعكاس هبوطي -)")
                    bias -= 2

            # Head & Shoulders — رأس وكتفان (هبوطي)
            if len(h) >= 30:
                ls = float(h.iloc[-20])  # الكتف الأيسر
                hd = float(h.iloc[-10])  # الرأس
                rs = float(h.iloc[-1])   # الكتف الأيمن
                if hd > ls and hd > rs and abs(ls - rs) / hd < 0.05:
                    neckline = min(float(l.iloc[-15]), float(l.iloc[-5]))
                    if float(c.iloc[-1]) < neckline:
                        detected.append("Head & Shoulders 🎭 [1D] (انعكاس هبوطي -)")
                        bias -= 3

            # Inverse H&S — رأس وكتفان معكوس (صعودي)
            if len(l) >= 30:
                ls2 = float(l.iloc[-20])
                hd2 = float(l.iloc[-10])
                rs2 = float(l.iloc[-1])
                if hd2 < ls2 and hd2 < rs2 and abs(ls2 - rs2) / abs(hd2) < 0.05:
                    neckline2 = max(float(h.iloc[-15]), float(h.iloc[-5]))
                    if float(c.iloc[-1]) > neckline2:
                        detected.append("Inv. Head & Shoulders 🎭↑ [1D] (انعكاس صعودي +)")
                        bias += 3

            # Cup & Handle — كوب وقبضة (صعودي)
            if len(c) >= 40:
                cup_left  = float(c.iloc[-40])
                cup_bottom= float(c.iloc[-20:].min())
                cup_right = float(c.iloc[-5])
                handle    = float(c.iloc[-1])
                if (abs(cup_left - cup_right) / cup_left < 0.03 and
                        cup_bottom < cup_left * 0.92 and
                        handle > cup_bottom and handle < cup_right):
                    detected.append("Cup & Handle ☕ [1D] (اختراق صعودي +)")
                    bias += 3

            # Rising Wedge — إسفين صاعد (هبوطي)
            if len(h) >= 20:
                h_slope = (float(h.iloc[-1]) - float(h.iloc[-10])) / 10
                l_slope = (float(l.iloc[-1]) - float(l.iloc[-10])) / 10
                if h_slope > 0 and l_slope > 0 and l_slope > h_slope:
                    detected.append("Rising Wedge 📐↗ [1D] (إسفين صاعد هبوطي -)")
                    bias -= 2

            # Falling Wedge — إسفين هابط (صعودي)
            if len(h) >= 20:
                h_sl = (float(h.iloc[-1]) - float(h.iloc[-10])) / 10
                l_sl = (float(l.iloc[-1]) - float(l.iloc[-10])) / 10
                if h_sl < 0 and l_sl < 0 and l_sl < h_sl:
                    detected.append("Falling Wedge 📐↘ [1D] (إسفين هابط صعودي +)")
                    bias += 2

            # Flag Pattern — نمط العلم
            if len(c) >= 20:
                prior_move = (float(c.iloc[-10]) - float(c.iloc[-20])) / float(c.iloc[-20]) * 100
                recent_range = (float(h.iloc[-5:].max()) - float(l.iloc[-5:].min())) / float(c.iloc[-5]) * 100
                if prior_move > 5 and recent_range < 2:
                    detected.append("Bull Flag 🚩 [1D] (استمرار صعودي +)")
                    bias += 2
                elif prior_move < -5 and recent_range < 2:
                    detected.append("Bear Flag 🚩 [1D] (استمرار هبوطي -)")
                    bias -= 2

            # Symmetrical Triangle — مثلث متماثل
            if len(h) >= 20:
                h_s = (float(h.iloc[-1]) - float(h.iloc[-10])) / 10
                l_s = (float(l.iloc[-1]) - float(l.iloc[-10])) / 10
                if h_s < -0.001 and l_s > 0.001:
                    detected.append("Symmetrical Triangle 🔺 [1D] (ترقب اختراق)")

            summary = (
                "أنماط مخططية صعودية قوية 🟢🟢" if bias >= 3 else
                "ميل مخططي صعودي 🟢"             if bias >= 1 else
                "أنماط مخططية هبوطية قوية 🔴🔴"  if bias <= -3 else
                "ميل مخططي هبوطي 🔴"              if bias <= -1 else
                "أنماط محايدة ⚖️"
            )

            return {"detected": detected, "bias": bias, "summary": summary,
                    "count": len(detected), "timeframe": "1D"}

        except Exception as e:
            return {"detected": [], "bias": 0, "summary": "غير متاح",
                    "count": 0, "timeframe": "1D"}

    # ============================================================
    # 4H — ADX (قوة الاتجاه)
    # ============================================================
    def _calculate_adx(self, high: pd.Series, low: pd.Series,
                       close: pd.Series, period: int = 14) -> dict:
        try:
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)

            up   = high.diff()
            down = -low.diff()
            dm_p = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=close.index)
            dm_m = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=close.index)

            atr14 = tr.ewm(alpha=1/period, min_periods=period).mean()
            dip   = dm_p.ewm(alpha=1/period, min_periods=period).mean() / atr14 * 100
            dim   = dm_m.ewm(alpha=1/period, min_periods=period).mean() / atr14 * 100
            dx    = (dip - dim).abs() / (dip + dim).replace(0, np.nan) * 100
            adx_v = float(dx.ewm(alpha=1/period, min_periods=period).mean().iloc[-1])
            dip_v = float(dip.iloc[-1])
            dim_v = float(dim.iloc[-1])

            strength = (
                "اتجاه قوي جداً 🔥"              if adx_v >= 40 else
                "اتجاه واضح ✅"                   if adx_v >= 25 else
                "اتجاه ضعيف ⚠️"                  if adx_v >= 20 else
                "سوق عرضي — تجنب الإشارات ❌"
            )
            direction = "صعودي 📈" if dip_v > dim_v else "هبوطي 📉"

            return {
                "adx"      : round(adx_v, 2),
                "dip"      : round(dip_v, 2),
                "dim"      : round(dim_v, 2),
                "strength" : strength,
                "direction": direction,
                "tradeable": adx_v >= 20
            }
        except:
            return {"adx": None, "strength": "غير متاح", "tradeable": True}

    # ============================================================
    # 1D — الدعم والمقاومة (القمم والقيعان المحلية)
    # ============================================================
    def _calculate_support_resistance(self, high: pd.Series, low: pd.Series,
                                       close: pd.Series,
                                       lookback: int = 60) -> dict:
        try:
            price = float(close.iloc[-1])
            h     = high.iloc[-lookback:]
            l     = low.iloc[-lookback:]

            resistance_levels, support_levels = [], []

            for i in range(2, len(h) - 2):
                if (h.iloc[i] > h.iloc[i-1] and h.iloc[i] > h.iloc[i-2] and
                        h.iloc[i] > h.iloc[i+1] and h.iloc[i] > h.iloc[i+2]):
                    resistance_levels.append(float(h.iloc[i]))
                if (l.iloc[i] < l.iloc[i-1] and l.iloc[i] < l.iloc[i-2] and
                        l.iloc[i] < l.iloc[i+1] and l.iloc[i] < l.iloc[i+2]):
                    support_levels.append(float(l.iloc[i]))

            nearest_support    = max((s for s in support_levels    if s < price), default=None)
            nearest_resistance = min((r for r in resistance_levels if r > price), default=None)

            dist_s = ((price - nearest_support)    / price * 100) if nearest_support    else None
            dist_r = ((nearest_resistance - price) / price * 100) if nearest_resistance else None

            near_s = dist_s is not None and dist_s < 1.5
            near_r = dist_r is not None and dist_r < 1.5

            return {
                "nearest_support"   : round(nearest_support,    4) if nearest_support    else None,
                "nearest_resistance": round(nearest_resistance,  4) if nearest_resistance else None,
                "dist_to_support"   : round(dist_s, 2)              if dist_s             else None,
                "dist_to_resistance": round(dist_r, 2)              if dist_r             else None,
                "near_support"      : near_s,
                "near_resistance"   : near_r,
                "context"           : (
                    "🟢 قريب من دعم — فرصة شراء محتملة" if near_s else
                    "🔴 قريب من مقاومة — احتمال رفض"    if near_r else
                    "⚖️ في منطقة محايدة"
                )
            }
        except:
            return {"nearest_support": None, "nearest_resistance": None,
                    "context": "غير متاح"}

    # ============================================================
    # 4H — ADX: قوة الاتجاه
    # ADX ≥ 25 → اتجاه قوي | ADX < 20 → سوق عرضي (تجنب)
    # ============================================================
    def _calculate_adx(self, high: pd.Series, low: pd.Series,
                       close: pd.Series, period: int = 14) -> dict:
        try:
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)

            up   = high.diff()
            down = -low.diff()

            dm_plus  = pd.Series(
                np.where((up > down) & (up > 0), up, 0.0), index=close.index
            )
            dm_minus = pd.Series(
                np.where((down > up) & (down > 0), down, 0.0), index=close.index
            )

            atr14 = tr.ewm(alpha=1/period, min_periods=period).mean()
            dip   = (dm_plus.ewm(alpha=1/period,  min_periods=period).mean()
                     / atr14 * 100)
            dim   = (dm_minus.ewm(alpha=1/period, min_periods=period).mean()
                     / atr14 * 100)

            dx      = ((dip - dim).abs() / (dip + dim).replace(0, np.nan) * 100)
            adx_val = float(dx.ewm(alpha=1/period, min_periods=period).mean().iloc[-1])
            dip_val = float(dip.iloc[-1])
            dim_val = float(dim.iloc[-1])

            if adx_val >= 40:
                strength = "اتجاه قوي جداً 🔥"
            elif adx_val >= 25:
                strength = "اتجاه واضح ✅"
            elif adx_val >= 20:
                strength = "اتجاه ضعيف ⚠️"
            else:
                strength = "سوق عرضي ❌"

            direction = "صعودي 📈" if dip_val > dim_val else "هبوطي 📉"

            return {
                "adx"      : round(adx_val, 2),
                "dip"      : round(dip_val, 2),
                "dim"      : round(dim_val, 2),
                "strength" : strength,
                "direction": direction,
                "tradeable": adx_val >= 20,
                "timeframe": "4H"
            }
        except Exception as e:
            return {"adx": None, "strength": "غير متاح",
                    "tradeable": True, "timeframe": "4H"}

    # ============================================================
    # 1D — الدعم والمقاومة
    # يحدد أقرب مستويات دعم ومقاومة من القمم/القيعان المحلية
    # ============================================================
    def _calculate_support_resistance(self, high: pd.Series, low: pd.Series,
                                       close: pd.Series,
                                       lookback: int = 60) -> dict:
        try:
            price = float(close.iloc[-1])
            h     = high.iloc[-lookback:]
            l     = low.iloc[-lookback:]

            resistance_levels = []
            support_levels    = []

            for i in range(2, len(h) - 2):
                # قمة محلية
                if (h.iloc[i] > h.iloc[i-1] and h.iloc[i] > h.iloc[i-2] and
                        h.iloc[i] > h.iloc[i+1] and h.iloc[i] > h.iloc[i+2]):
                    resistance_levels.append(float(h.iloc[i]))
                # قاع محلي
                if (l.iloc[i] < l.iloc[i-1] and l.iloc[i] < l.iloc[i-2] and
                        l.iloc[i] < l.iloc[i+1] and l.iloc[i] < l.iloc[i+2]):
                    support_levels.append(float(l.iloc[i]))

            supports_below    = [s for s in support_levels    if s < price]
            resistances_above = [r for r in resistance_levels if r > price]

            nearest_support    = max(supports_below)    if supports_below    else None
            nearest_resistance = min(resistances_above) if resistances_above else None

            dist_to_support    = ((price - nearest_support)    / price * 100
                                  if nearest_support    else None)
            dist_to_resistance = ((nearest_resistance - price) / price * 100
                                  if nearest_resistance else None)

            near_support    = dist_to_support    is not None and dist_to_support    < 1.5
            near_resistance = dist_to_resistance is not None and dist_to_resistance < 1.5

            context = (
                "🟢 قريب من دعم — فرصة شراء محتملة" if near_support else
                "🔴 قريب من مقاومة — احتمال رفض"    if near_resistance else
                "⚖️ في منطقة محايدة"
            )

            return {
                "nearest_support"    : round(nearest_support,    4) if nearest_support    else None,
                "nearest_resistance" : round(nearest_resistance,  4) if nearest_resistance else None,
                "dist_to_support"    : round(dist_to_support,     2) if dist_to_support    else None,
                "dist_to_resistance" : round(dist_to_resistance,  2) if dist_to_resistance else None,
                "near_support"       : near_support,
                "near_resistance"    : near_resistance,
                "context"            : context,
                "timeframe"          : "1D"
            }
        except Exception as e:
            return {"nearest_support": None, "nearest_resistance": None,
                    "context": "غير متاح", "timeframe": "1D"}

    # ============================================================
    # 15M — تأكيد توقيت الدخول (معزز وليس شرطاً)
    # ============================================================
    def check_15m_confirmation(self, symbol: str, direction: str) -> dict:
        """
        يتحقق من توافق الزخم القصير مع اتجاه الإشارة.
        لا يوقف الإشارة — فقط يرفع أو يخفض الثقة قليلاً.

        النتيجة:
          confirmed  → +5% ثقة  — "الزخم القصير مواتٍ ✅"
          neutral    →  0% ثقة  — "الزخم محايد ⚖️"
          conflicting → -5% ثقة — "الزخم القصير معاكس ⚠️"
        """
        try:
            asset_type = self.detect_asset_type(symbol)

            # جلب بيانات 15M
            if asset_type == "crypto":
                ohlcv = self.crypto_exchange.fetch_ohlcv(
                    symbol, timeframe="15m", limit=60
                )
                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp','open','high','low','close','volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
            else:
                tk = yf.Ticker(symbol)
                df = tk.history(period="5d", interval="15m")
                if df.empty:
                    return self._mtf_unavailable()
                df.columns = [c.lower() for c in df.columns]

            if df.empty or len(df) < 20:
                return self._mtf_unavailable()

            close = df['close']
            high  = df['high']
            low   = df['low']
            price = float(close.iloc[-1])

            # RSI (14)
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss
            rsi   = float((100 - (100 / (1 + rs))).iloc[-1])

            # MA20
            ma20  = float(close.rolling(20).mean().iloc[-1])

            # MACD histogram
            ema12     = close.ewm(span=12).mean()
            ema26     = close.ewm(span=26).mean()
            macd_hist = float((ema12 - ema26 - (ema12 - ema26).ewm(span=9).mean()).iloc[-1])

            # تقييم كل مؤشر مقابل الاتجاه
            if direction == "BUY":
                checks = {
                    "rsi"  : rsi > 45,
                    "ma20" : price > ma20,
                    "macd" : macd_hist > 0,
                }
            elif direction == "SELL":
                checks = {
                    "rsi"  : rsi < 55,
                    "ma20" : price < ma20,
                    "macd" : macd_hist < 0,
                }
            else:
                return self._mtf_unavailable()

            passed = sum(checks.values())

            # الحكم
            if passed == 3:
                status       = "confirmed"
                label        = "الزخم القصير مواتٍ ✅"
                confidence_delta = +5
            elif passed == 2:
                status       = "neutral"
                label        = "الزخم محايد ⚖️"
                confidence_delta = 0
            else:
                status       = "conflicting"
                label        = "الزخم القصير معاكس ⚠️"
                confidence_delta = -5

            return {
                "available"        : True,
                "status"           : status,
                "label"            : label,
                "confidence_delta" : confidence_delta,
                "rsi_15m"          : round(rsi, 1),
                "above_ma20"       : price > ma20,
                "macd_positive"    : macd_hist > 0,
                "checks_passed"    : passed,
            }

        except Exception as e:
            return self._mtf_unavailable()

    def _mtf_unavailable(self) -> dict:
        return {
            "available"        : False,
            "status"           : "neutral",
            "label"            : "بيانات 15M غير متاحة",
            "confidence_delta" : 0,
        }

    # ============================================================
    # تعدد الأطر الزمنية — ملخص توافق الأطر
    # (البيانات مجلوبة مسبقاً في _fetch_crypto / _fetch_yfinance)
    # التأكيد على أطر متعددة = إشارة أكثر موثوقية
    # ============================================================
    def fetch_multi_timeframe(self, symbol: str,
                              dfs: dict = None) -> dict:
        """
        يحسب توافق الأطر الزمنية من البيانات المجلوبة مسبقاً
        dfs = {"1H": df, "4H": df, "1D": df}  ← من fetch_market_data
        إذا لم تُمرَّر، يجلبها مجدداً (احتياط)
        """
        if dfs is None:
            # احتياط فقط — الأفضل تمريرها من fetch_market_data
            asset_type = self.detect_asset_type(symbol)
            dfs = {}
            try:
                if asset_type == "crypto":
                    for tf, label, limit in [("1h","1H",200),("4h","4H",150),("1d","1D",200)]:
                        ohlcv = self.crypto_exchange.fetch_ohlcv(symbol, tf, limit=limit)
                        df = pd.DataFrame(ohlcv,
                            columns=['timestamp','open','high','low','close','volume'])
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                        df.set_index('timestamp', inplace=True)
                        dfs[label] = df
                else:
                    tk = yf.Ticker(symbol)
                    df1h = tk.history(period="60d", interval="1h")
                    df1h.columns = [c.lower() for c in df1h.columns]
                    dfs["1H"] = df1h
                    dfs["4H"] = df1h.resample("4h").agg({
                        'open':'first','high':'max','low':'min',
                        'close':'last','volume':'sum'}).dropna()
                    df1d = tk.history(period="1y", interval="1d")
                    df1d.columns = [c.lower() for c in df1d.columns]
                    dfs["1D"] = df1d
            except Exception as e:
                return {"available": False, "error": str(e)}

        timeframes = {
            label: self._tf_summary(df)
            for label, df in dfs.items()
            if not df.empty
        }

        directions = [v.get("direction") for v in timeframes.values()
                      if v.get("direction") and v["direction"] != "NEUTRAL"]
        buy_count  = directions.count("BUY")
        sell_count = directions.count("SELL")

        if buy_count == 3:
            alignment, score = "توافق صعودي كامل 🟢🟢🟢", 3
        elif sell_count == 3:
            alignment, score = "توافق هبوطي كامل 🔴🔴🔴", -3
        elif buy_count == 2:
            alignment, score = "ميل صعودي 🟢🟢", 2
        elif sell_count == 2:
            alignment, score = "ميل هبوطي 🔴🔴", -2
        else:
            alignment, score = "تعارض بين الأطر ⚠️", 0

        return {
            "available"    : True,
            "timeframes"   : timeframes,
            "alignment"    : alignment,
            "score"        : score,
            "strong_signal": abs(score) == 3
        }

    def _tf_summary(self, df: pd.DataFrame) -> dict:
        """ملخص سريع لكل إطار زمني"""
        if df is None or df.empty or len(df) < 10:
            return {"direction": None, "rsi": None, "trend": "N/A"}

        close = df['close']
        price = float(close.iloc[-1])

        # RSI سريع
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - (100 / (1 + rs))).iloc[-1])

        # MA trend
        ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else price
        ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else price

        # اتجاه
        if price > ma20 > ma50 and rsi > 50:
            direction = "BUY"
            trend     = "صعودي 📈"
        elif price < ma20 < ma50 and rsi < 50:
            direction = "SELL"
            trend     = "هبوطي 📉"
        else:
            direction = "NEUTRAL"
            trend     = "محايد ⚖️"

        return {
            "direction": direction,
            "rsi"      : round(rsi, 1),
            "price"    : round(price, 4),
            "ma20"     : round(ma20, 4),
            "trend"    : trend
        }

    # ============================================================
    # بيانات الاقتصاد الكلي عبر FRED
    # ============================================================
    def fetch_macro_data(self) -> dict:
        if not self.fred_api_key:
            return {"available": False}

        series = {
            "fed_rate"    : "FEDFUNDS",
            "inflation"   : "CPIAUCSL",
            "unemployment": "UNRATE",
            "gdp_growth"  : "A191RL1Q225SBEA"
        }

        macro = {}
        for name, series_id in series.items():
            try:
                url = (
                    f"https://api.stlouisfed.org/fred/series/observations"
                    f"?series_id={series_id}"
                    f"&api_key={self.fred_api_key}"
                    f"&file_type=json&limit=2&sort_order=desc"
                )
                r    = requests.get(url, timeout=10)
                data = r.json()
                obs  = data.get("observations", [])
                if obs:
                    macro[name] = float(obs[0].get("value", 0))
            except:
                macro[name] = None

        return macro

    # ============================================================
    # تحليل السيولة (من مهارات CloddsBot)
    # ============================================================
    def liquidity_analysis(self, symbol: str) -> dict:
        asset_type = self.detect_asset_type(symbol)

        if asset_type != "crypto":
            return {"available": False, "reason": "السيولة اللحظية للكريبتو فقط"}

        try:
            ob         = self.crypto_exchange.fetch_order_book(symbol, limit=20)
            bid_vol    = sum(b[1] for b in ob['bids'][:10])
            ask_vol    = sum(a[1] for a in ob['asks'][:10])
            imbalance  = bid_vol / ask_vol if ask_vol else 1
            spread     = (ob['asks'][0][0] - ob['bids'][0][0]) / ob['bids'][0][0] * 100

            if imbalance > 1.5:
                pressure = "ضغط شراء قوي 🟢"
            elif imbalance < 0.67:
                pressure = "ضغط بيع قوي 🔴"
            else:
                pressure = "متوازن ⚖️"

            return {
                "available" : True,
                "imbalance" : round(imbalance, 3),
                "pressure"  : pressure,
                "spread_pct": round(spread, 4),
                "bid_depth" : round(bid_vol, 2),
                "ask_depth" : round(ask_vol, 2)
            }
        except Exception as e:
            return {"available": False, "reason": str(e)}
