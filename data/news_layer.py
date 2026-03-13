"""
طبقة الأخبار والمشاعر — بيانات حقيقية مجانية
──────────────────────────────────────────────
① RSS: Yahoo Finance / Google News لكل رمز
② Fear & Greed Index للكريبتو (alternative.me)
③ Keyword Scoring بدون LLM (سريع ومجاني)
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from functools import lru_cache


# ============================================================
# ثوابت التحليل
# ============================================================
BULLISH_KEYWORDS = [
    "surge", "rally", "jump", "gain", "rise", "bull", "breakout",
    "high", "record", "strong", "beat", "outperform", "upgrade",
    "buy", "positive", "growth", "profit", "revenue", "اختراق",
    "ارتفاع", "صعود", "قفز", "ربح", "قوي", "شراء"
]

BEARISH_KEYWORDS = [
    "drop", "fall", "plunge", "decline", "crash", "bear", "breakdown",
    "low", "weak", "miss", "underperform", "downgrade", "sell",
    "negative", "loss", "debt", "regulation", "ban", "هبوط",
    "انخفاض", "تراجع", "خسارة", "ضعيف", "بيع", "حظر"
]

CACHE_TTL = 900  # 15 دقيقة


# ============================================================
# دالة جلب URL آمنة بدون مكتبات خارجية
# ============================================================
def _safe_fetch(url: str, timeout: int = 8) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ============================================================
# Fear & Greed Index (كريبتو فقط)
# ============================================================
_fg_cache: dict = {}

def get_fear_greed() -> dict:
    """
    يجلب مؤشر الخوف والجشع من alternative.me
    مجاني + لا يحتاج API key
    """
    global _fg_cache
    now = time.time()

    if _fg_cache and now - _fg_cache.get("_ts", 0) < CACHE_TTL:
        return _fg_cache

    try:
        raw  = _safe_fetch("https://api.alternative.me/fng/?limit=1&format=json")
        data = json.loads(raw)
        entry = data["data"][0]
        value = int(entry["value"])
        label = entry["value_classification"]

        # تفسير القيمة
        if value <= 25:
            sentiment = "خوف شديد 😱"
            signal    = "BUY_BIAS"   # فرصة شراء مضادة
        elif value <= 45:
            sentiment = "خوف 😨"
            signal    = "BUY_BIAS"
        elif value <= 55:
            sentiment = "محايد ⚖️"
            signal    = "NEUTRAL"
        elif value <= 75:
            sentiment = "جشع 🤑"
            signal    = "SELL_BIAS"
        else:
            sentiment = "جشع شديد 🔥"
            signal    = "SELL_BIAS"  # تحذير من الشراء

        result = {
            "available" : True,
            "value"     : value,
            "label"     : label,
            "sentiment" : sentiment,
            "signal"    : signal,
            "_ts"       : now
        }
        _fg_cache = result
        return result

    except Exception:
        return {"available": False, "value": 50, "sentiment": "غير متاح", "signal": "NEUTRAL"}


# ============================================================
# RSS News Fetcher
# ============================================================
_news_cache: dict = {}

def _clean_symbol_for_search(symbol: str) -> str:
    """تحويل رمز التداول لكلمة بحث مفهومة"""
    mapping = {
        "BTC/USDT" : "Bitcoin BTC",
        "ETH/USDT" : "Ethereum ETH",
        "SOL/USDT" : "Solana SOL",
        "EURUSD=X" : "EUR USD forex",
        "GBPUSD=X" : "GBP USD forex",
        "USDJPY=X" : "USD JPY forex",
        "GC=F"     : "Gold futures",
        "CL=F"     : "Crude Oil futures",
        "SI=F"     : "Silver futures",
        "^GSPC"    : "S&P 500",
        "^DJI"     : "Dow Jones",
        "^IXIC"    : "NASDAQ",
    }
    return mapping.get(symbol, symbol.replace("/USDT", "").replace("=X", "").replace("^", ""))


def fetch_rss_headlines(symbol: str, max_items: int = 8) -> list:
    """
    يجلب آخر العناوين من Yahoo Finance RSS
    مجاني تماماً بدون API key
    """
    global _news_cache
    now    = time.time()
    cached = _news_cache.get(symbol)

    if cached and now - cached.get("_ts", 0) < CACHE_TTL:
        return cached["headlines"]

    query    = _clean_symbol_for_search(symbol)
    encoded  = urllib.parse.quote(query)
    url      = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={encoded}&region=US&lang=en-US"

    headlines = []
    raw       = _safe_fetch(url)

    if raw:
        try:
            root = ET.fromstring(raw)
            for item in root.findall(".//item")[:max_items]:
                title = item.findtext("title", "").strip()
                pub   = item.findtext("pubDate", "").strip()
                if title:
                    headlines.append({"title": title, "pub": pub})
        except Exception:
            pass

    # fallback → Google News RSS
    if not headlines:
        url2 = f"https://news.google.com/rss/search?q={encoded}+stock+finance&hl=en&gl=US&ceid=US:en"
        raw2 = _safe_fetch(url2)
        if raw2:
            try:
                root = ET.fromstring(raw2)
                for item in root.findall(".//item")[:max_items]:
                    title = item.findtext("title", "").strip()
                    pub   = item.findtext("pubDate", "").strip()
                    if title:
                        headlines.append({"title": title, "pub": pub})
            except Exception:
                pass

    _news_cache[symbol] = {"headlines": headlines, "_ts": now}
    return headlines


# ============================================================
# Keyword Scoring (بدون LLM)
# ============================================================
def score_headlines(headlines: list) -> dict:
    """
    يحلل العناوين بكلمات مفتاحية ويعطي درجة مشاعر
    """
    if not headlines:
        return {
            "available"  : False,
            "score"      : 0,
            "sentiment"  : "لا أخبار",
            "signal"     : "NEUTRAL",
            "bullish_n"  : 0,
            "bearish_n"  : 0,
            "headlines"  : []
        }

    bull = 0
    bear = 0
    all_text = " ".join(h["title"].lower() for h in headlines)

    for kw in BULLISH_KEYWORDS:
        bull += all_text.count(kw.lower())
    for kw in BEARISH_KEYWORDS:
        bear += all_text.count(kw.lower())

    total = bull + bear
    if total == 0:
        score     = 0
        sentiment = "محايد ⚖️"
        signal    = "NEUTRAL"
    else:
        score = round((bull - bear) / total * 100)
        if score >= 40:
            sentiment = "إيجابي قوي 🟢"
            signal    = "BUY_BIAS"
        elif score >= 15:
            sentiment = "إيجابي 🟩"
            signal    = "BUY_BIAS"
        elif score <= -40:
            sentiment = "سلبي قوي 🔴"
            signal    = "SELL_BIAS"
        elif score <= -15:
            sentiment = "سلبي 🟥"
            signal    = "SELL_BIAS"
        else:
            sentiment = "محايد ⚖️"
            signal    = "NEUTRAL"

    return {
        "available" : True,
        "score"     : score,
        "sentiment" : sentiment,
        "signal"    : signal,
        "bullish_n" : bull,
        "bearish_n" : bear,
        "headlines" : [h["title"] for h in headlines[:4]]  # أول 4 فقط
    }


# ============================================================
# الواجهة الرئيسية — جلب كل بيانات الأخبار/المشاعر
# ============================================================
def get_news_sentiment(symbol: str, asset_type: str = "") -> dict:
    """
    يُعيد حزمة كاملة من بيانات الأخبار/المشاعر
    تُمرَّر مباشرة لوكلاء الأخبار والمشاعر
    """
    headlines   = fetch_rss_headlines(symbol)
    news_score  = score_headlines(headlines)

    result = {
        "news"      : news_score,
        "fg_index"  : {"available": False},
        "summary"   : news_score["sentiment"],
        "signal"    : news_score["signal"],
    }

    # Fear & Greed للكريبتو فقط
    if asset_type == "crypto" or "USDT" in symbol or "BTC" in symbol:
        fg = get_fear_greed()
        result["fg_index"] = fg
        # دمج الإشارتين
        if fg["available"]:
            if news_score["signal"] == fg["signal"]:
                result["signal"]  = news_score["signal"]
                result["summary"] = f"{news_score['sentiment']} + F&G={fg['value']} {fg['sentiment']}"
            else:
                result["signal"]  = "NEUTRAL"
                result["summary"] = f"تعارض: أخبار={news_score['sentiment']} / F&G={fg['value']}"

    return result
