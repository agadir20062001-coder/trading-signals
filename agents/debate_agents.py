"""
نظام النقاش بين الوكلاء — مستوحى من TradingAgents
الجولة 1: كل وكيل يقدم تحليله وموقفه
الجولة 2: النقاش والرد على الحجج المعارضة
الحكم:  وكيل القاضي يزن الحجج بالقوة والكثرة
"""

import json
import os
import time
from dotenv import load_dotenv
from data.news_layer import get_news_sentiment

load_dotenv()


# ============================================================
# إعداد النموذج
# ============================================================
def get_llm():
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            temperature=0.2,
            max_tokens=1500
        )
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            temperature=0.2
        )


# ============================================================
# تعريف الوكلاء الخمسة بشخصياتهم
# ============================================================
ANALYST_PERSONAS = {

    "technical": {
        "name"    : "المحلل التقني 📊",
        "role"    : "محلل تقني",
        "style"   : "دقيق وحازم، يستند إلى الأرقام والمؤشرات فقط",
        "focus"   : (
            "RSI، MACD، Bollinger، ADX، دعم/مقاومة، "
            "الأنماط الفنية، تعدد الأطر الزمنية، حجم التداول"
        ),
    },
    "news": {
        "name"    : "محلل الأخبار 📰",
        "role"    : "محلل أحداث",
        "style"   : "يربط الأحداث بحركة السعر، يبحث عن المحفزات",
        "focus"   : (
            "أخبار الشركة أو الأصل، إعلانات الأرباح، "
            "الأحداث التنظيمية، أخبار القطاع، المحفزات قصيرة الأجل"
        ),
    },
    "sentiment": {
        "name"    : "محلل المشاعر 💬",
        "role"    : "قارئ نبض السوق",
        "style"   : "يقيس درجة الخوف والجشع، يكتشف التطرف",
        "focus"   : (
            "مشاعر المتداولين، الزخم السعري، التطرف (تشبع شراء/بيع)، "
            "اتجاه السوق العام (Risk-on/off)"
        ),
    },
    "fundamentals": {
        "name"    : "محلل الأساسيات 📈",
        "role"    : "محلل قيمة",
        "style"   : "يبحث عن الفجوة بين السعر والقيمة الحقيقية",
        "focus"   : (
            "للأسهم: PE، EPS، نمو الإيرادات. "
            "للكريبتو: حالة الشبكة، التبني. "
            "للفوركس: الفوارق الاقتصادية. للسلع: العرض والطلب"
        ),
    },
    "macro": {
        "name"    : "محلل الاقتصاد الكلي 🌍",
        "role"    : "محلل جيوسياسي",
        "style"   : "يرى الصورة الكبيرة ويربط القرارات الاقتصادية بالأسواق",
        "focus"   : (
            "أسعار الفائدة، التضخم، البطالة، "
            "مرحلة الدورة الاقتصادية، الدولار، قرارات الفيدرالي"
        ),
    },
}


# ============================================================
# ملخص بيانات السوق (يُستخدم في كل جولة)
# ============================================================
def _market_brief(symbol: str, market_data: dict,
                  macro_data: dict, mtf: dict = None,
                  news_data: dict = None) -> str:
    ind = market_data.get("indicators", {})
    adx = ind.get("adx", {})
    sr  = ind.get("sr",  {})
    pat = ind.get("patterns", {})

    mtf_text = "غير متاح"
    if mtf and mtf.get("available"):
        tfs = mtf.get("timeframes", {})
        mtf_text = (
            f"1H:{tfs.get('1H',{}).get('trend','N/A')} "
            f"| 4H:{tfs.get('4H',{}).get('trend','N/A')} "
            f"| 1D:{tfs.get('1D',{}).get('trend','N/A')} "
            f"— {mtf.get('alignment','N/A')}"
        )

    # قسم الأخبار والمشاعر
    news_text = "لا بيانات أخبار"
    if news_data:
        news  = news_data.get("news", {})
        fg    = news_data.get("fg_index", {})
        hdls  = news.get("headlines", [])
        hdl_text = "\n".join(f"  • {h}" for h in hdls[:3]) if hdls else "  لا عناوين"
        fg_text  = f"F&G={fg['value']} ({fg['sentiment']})" if fg.get("available") else ""
        news_text = (
            f"المشاعر: {news_data.get('summary','غير متاح')} {fg_text}\n"
            f"الإشارة: {news_data.get('signal','NEUTRAL')}\n"
            f"آخر العناوين:\n{hdl_text}"
        )

    return f"""
═══ ملف الأصل: {symbol} ({market_data.get('type','').upper()}) ═══
السعر: {market_data.get('price','N/A')} | التغير 24h: {market_data.get('change_24h',0):+.2f}%

[ المؤشرات التقنية ]
MA20={ind.get('ma20','N/A')} | MA50={ind.get('ma50','N/A')} | MA200={ind.get('ma200','N/A')}
RSI={ind.get('rsi','N/A')} | MACD_Hist={ind.get('macd_hist','N/A')} | BB%={ind.get('bb_pct','N/A')}
حجم_نسبي={ind.get('vol_ratio','N/A')}x | ATR={ind.get('atr_pct','N/A')}% | نظام={ind.get('regime','N/A')}
ADX={adx.get('adx','N/A')} ({adx.get('strength','N/A')}) | اتجاه={adx.get('direction','N/A')}

[ الدعم والمقاومة ]
دعم={sr.get('nearest_support','N/A')} (بُعد {sr.get('dist_to_support','N/A')}%)
مقاومة={sr.get('nearest_resistance','N/A')} (بُعد {sr.get('dist_to_resistance','N/A')}%)
{sr.get('context','N/A')}

[ الأنماط الفنية ]
{' | '.join(pat.get('detected',['لا أنماط'])) or 'لا أنماط'} — {pat.get('summary','N/A')}

[ الأطر الزمنية ]
{mtf_text}

[ الأخبار والمشاعر — بيانات حقيقية ]
{news_text}

[ الأساسيات ]
القطاع={market_data.get('sector','N/A')} | PE={market_data.get('pe_ratio','N/A')} | EPS={market_data.get('eps','N/A')}

[ الاقتصاد الكلي ]
فائدة={macro_data.get('fed_rate','N/A')}% | تضخم={macro_data.get('inflation','N/A')} | بطالة={macro_data.get('unemployment','N/A')}%
═══════════════════════════════════════════════
"""


# ============================================================
# الجولة 1 — كل وكيل يقدم تحليله وموقفه الأولي
# ============================================================
def round_1_opening(symbol: str, market_data: dict,
                    macro_data: dict, mtf: dict = None,
                    news_data: dict = None) -> dict:
    """
    كل وكيل يعطي تحليلاً مفصلاً وموقفاً واضحاً (BUY/SELL/HOLD)
    مع الأدلة التي يستند إليها
    """
    llm    = get_llm()
    brief  = _market_brief(symbol, market_data, macro_data, mtf, news_data)
    openings = {}

    print(f"\n  📋 الجولة 1 — التحليل الأولي...")

    for key, persona in ANALYST_PERSONAS.items():
        print(f"     ⏳ {persona['name']}...")

        prompt = f"""أنت {persona['name']} — {persona['style']}.
تخصصك الحصري: {persona['focus']}.

{brief}

قدّم تحليلك لـ {symbol} بهذا الهيكل الحرفي فقط — لا تضف أي شيء خارجه:

الموقف: [BUY أو SELL أو HOLD]
السبب: [جملة واحدة مكثفة من تخصصك]
أقوى دليل: [رقم أو نمط أو حدث واحد محدد]
أكبر مخاطرة: [جملة واحدة]

لا تتجاوز تخصصك. لا تكتب فقرات. أجب بالهيكل فقط."""

        try:
            resp     = llm.invoke([{"role": "user", "content": prompt}])
            analysis = resp.content.strip()
        except Exception as e:
            analysis = f"خطأ: {str(e)[:60]}"

        time.sleep(2)  # تجنب Rate limit

        # استخلاص الموقف
        text_upper = analysis.upper()
        if "BUY" in text_upper and "SELL" not in text_upper:
            stance = "BUY"
        elif "SELL" in text_upper and "BUY" not in text_upper:
            stance = "SELL"
        elif "HOLD" in text_upper:
            stance = "HOLD"
        else:
            # المزيد من الكلمات العربية
            if any(w in analysis for w in ["شراء", "ارتفاع", "صعود", "إيجابي"]):
                stance = "BUY"
            elif any(w in analysis for w in ["بيع", "انخفاض", "هبوط", "سلبي"]):
                stance = "SELL"
            else:
                stance = "HOLD"

        # استخلاص حقول الهيكل المنظم
        lines      = analysis.split("\n")
        structured = {}
        for line in lines:
            for field in ["الموقف", "السبب", "أقوى دليل", "أكبر مخاطرة"]:
                if line.strip().startswith(field + ":"):
                    structured[field] = line.split(":", 1)[1].strip()

        openings[key] = {
            "name"      : persona["name"],
            "stance"    : stance,
            "analysis"  : analysis,          # كامل للإيميل
            "structured": structured,         # مكثف للتيليغرام
        }
        print(f"     ✅ {persona['name']}: {stance}")

    return openings


# ============================================================
# الجولة 2 — النقاش: كل وكيل يرد على المعارضين
# ============================================================
def round_2_debate(symbol: str, openings: dict,
                   market_data: dict, macro_data: dict,
                   mtf: dict = None, news_data: dict = None) -> dict:
    """
    كل وكيل يقرأ مواقف الآخرين ويرد عليها:
    - يدافع عن موقفه بحجج إضافية
    - يرد على الحجج المعارضة
    - قد يُعدّل موقفه إذا اقتنع بحجج الآخرين
    """
    llm    = get_llm()
    brief  = _market_brief(symbol, market_data, macro_data, mtf, news_data)
    debates = {}

    print(f"\n  💬 الجولة 2 — النقاش والرد...")

    # ملخص مواقف الجولة الأولى
    openings_summary = "\n".join([
        f"• {v['name']}: {v['stance']}\n  \"{v['analysis'][:200]}...\""
        for k, v in openings.items()
    ])

    for key, persona in ANALYST_PERSONAS.items():
        print(f"     ⏳ {persona['name']} يرد...")

        my_opening = openings[key]

        # الوكلاء المعارضون
        opponents = [
            v for k, v in openings.items()
            if k != key and v["stance"] != my_opening["stance"]
        ]
        supporters = [
            v for k, v in openings.items()
            if k != key and v["stance"] == my_opening["stance"]
        ]

        prompt = f"""أنت {persona['name']} — {persona['style']}.

{brief}

=== مواقف الزملاء (الجولة الأولى) ===
{openings_summary}

=== موقفك الأولي ===
موقفك: {my_opening['stance']}
تحليلك: {my_opening['analysis']}

المؤيدون لك ({len(supporters)}): {', '.join(v['name'] for v in supporters) or 'لا أحد'}
المعارضون لك ({len(opponents)}): {', '.join(v['name'] for v in opponents) or 'لا أحد'}

الآن:
1. رد على أقوى حجة معارضة لموقفك (إذا وجدت)
2. دعّم موقفك بحجة إضافية جديدة لم تذكرها في الجولة الأولى
3. هل تعدّل موقفك؟ (ابق على BUY/SELL/HOLD أو غيّره إن اقتنعت)
4. أعطِ موقفك النهائي بوضوح: FINAL_STANCE: [BUY/SELL/HOLD]

اكتب بثقة وإيجاز — 5-7 جمل."""

        try:
            resp  = llm.invoke([{"role": "user", "content": prompt}])
            reply = resp.content.strip()
        except Exception as e:
            reply = f"خطأ: {str(e)[:60]}"

        time.sleep(2)  # تجنب Rate limit

        # استخلاص الموقف النهائي
        final_stance = my_opening["stance"]  # افتراضي: الموقف الأولي
        if "FINAL_STANCE:" in reply.upper():
            parts = reply.upper().split("FINAL_STANCE:")
            if len(parts) > 1:
                extracted = parts[1].strip()[:10]
                if "BUY"  in extracted: final_stance = "BUY"
                elif "SELL" in extracted: final_stance = "SELL"
                elif "HOLD" in extracted: final_stance = "HOLD"

        changed = final_stance != my_opening["stance"]
        if changed:
            print(f"     🔄 {persona['name']}: {my_opening['stance']} → {final_stance}")
        else:
            print(f"     ✅ {persona['name']}: يُثبّت {final_stance}")

        debates[key] = {
            "name"         : persona["name"],
            "initial_stance": my_opening["stance"],
            "final_stance" : final_stance,
            "changed_mind" : changed,
            "debate_reply" : reply,
        }

    return debates


# ============================================================
# الحكم النهائي — وكيل القاضي
# ============================================================
def judge_verdict(symbol: str, openings: dict,
                  debates: dict, market_data: dict) -> dict:
    """
    القاضي يقرأ كل النقاش ويحكم بناءً على:
    - قوة الحجج (لا مجرد العدد)
    - الكثرة بعد تعديل المواقف
    - جودة الأدلة المقدمة
    - الاتساق بين التحليلات المختلفة
    """
    llm = get_llm()

    # ملخص النقاش الكامل
    debate_transcript = ""
    for key in ANALYST_PERSONAS:
        op = openings[key]
        db = debates[key]
        debate_transcript += f"""
─── {op['name']} ───
الجولة 1: {op['stance']} — "{op['analysis'][:300]}"
الجولة 2: {db['final_stance']} {"(غيّر رأيه! ✦)" if db['changed_mind'] else ""} — "{db['debate_reply'][:300]}"
"""

    # عدد الأصوات النهائية
    final_votes = {}
    for key, db in debates.items():
        s = db["final_stance"]
        final_votes[s] = final_votes.get(s, 0) + 1

    prompt = f"""أنت القاضي المحايد في هذا النقاش التحليلي حول {symbol}.
لديك خبرة عميقة في الأسواق المالية وتحكيم النقاشات التحليلية.

=== النقاش الكامل ===
{debate_transcript}

=== ملخص الأصوات النهائية ===
{json.dumps(final_votes, ensure_ascii=False)}

=== سعر الأصل الحالي ===
{market_data.get('price', 'N/A')}

مهمتك: إصدار الحكم النهائي بناءً على:
1. قوة وجودة الحجج (ليس مجرد العدد)
2. من قدّم أدلة ملموسة وأرقاماً واضحة؟
3. من اضطر لتغيير رأيه تحت وطأة الحجج؟
4. هل هناك توافق أساسي رغم الخلاف السطحي؟
5. الكثرة بعد الأخذ بعين الاعتبار قوة كل حجة

أجب بـ JSON فقط — لا كلام إضافي:
{{
  "direction": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "vote_count": عدد المتفقين مع القرار,
  "winning_argument": "أقوى حجة دعمت القرار في جملة واحدة",
  "dissent_summary": "ملخص أقوى اعتراض في جملة واحدة أو null",
  "judge_reasoning": "تبرير الحكم في 2-3 جمل",
  "mind_changes": عدد من غيّروا رأيهم خلال النقاش,
  "send_signal": true إذا confidence >= 65 وdirection != HOLD وإلا false
}}"""

    try:
        resp    = llm.invoke([{"role": "user", "content": prompt}])
        content = resp.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        verdict = json.loads(content.strip())
        verdict["raw_votes"] = final_votes
        return verdict

    except Exception as e:
        # حكم احتياطي بالأغلبية
        majority = max(final_votes, key=final_votes.get)
        count    = final_votes[majority]
        return {
            "direction"       : majority,
            "confidence"      : 50 + count * 8,
            "vote_count"      : count,
            "winning_argument": "تعذّر استخراج تبرير",
            "dissent_summary" : None,
            "judge_reasoning" : f"خطأ في القاضي — الحكم بالأغلبية: {str(e)[:80]}",
            "mind_changes"    : 0,
            "send_signal"     : count >= 4 and majority != "HOLD",  # ← HOLD لا يُرسل أبداً
            "raw_votes"       : final_votes,
        }


# ============================================================
# تشغيل النقاش الكامل — 3 مراحل
# ============================================================
def run_debate(symbol: str, market_data: dict,
               macro_data: dict, mtf: dict = None) -> dict:
    """
    يشغّل النقاش الكامل ويُعيد نتيجة جاهزة للإرسال
    """
    print(f"\n{'─'*40}")
    print(f"⚖️  نقاش الوكلاء لـ {symbol}")
    print(f"{'─'*40}")

    # جلب الأخبار والمشاعر — مرة واحدة لكل الوكلاء
    print(f"  📰 جلب الأخبار والمشاعر...")
    asset_type = market_data.get("type", "")
    news_data  = get_news_sentiment(symbol, asset_type)
    if news_data.get("news", {}).get("available"):
        print(f"  📊 المشاعر: {news_data['summary']}")
    else:
        print(f"  📰 لا أخبار متاحة — الوكلاء يعتمدون على البيانات التقنية")

    # الجولة 1
    openings = round_1_opening(symbol, market_data, macro_data, mtf, news_data)

    # الجولة 2
    debates  = round_2_debate(symbol, openings, market_data, macro_data, mtf, news_data)

    # انتظار قبل القاضي لتجنب Rate limit
    print(f"\n  ⏳ انتظار 5 ثوانٍ قبل القاضي...")
    time.sleep(5)

    # الحكم
    print(f"\n  🏛️  القاضي يحكم...")
    verdict  = judge_verdict(symbol, openings, debates, market_data)

    direction   = verdict.get("direction", "HOLD")
    confidence  = verdict.get("confidence", 50)
    send_signal = verdict.get("send_signal", False)
    vote_count  = verdict.get("vote_count", 0)

    # HOLD لا يُرسل أبداً بغض النظر عن أي شيء آخر
    if direction == "HOLD":
        send_signal = False

    # تحديد قوة الإجماع
    if vote_count == 5 and confidence >= 80:
        strength       = "🔥 استثنائي"
        strength_level = "EXCEPTIONAL"
    elif vote_count >= 4 and confidence >= 65:
        strength       = "✅ قوي"
        strength_level = "STRONG"
    elif vote_count == 3 and confidence >= 55:
        strength       = "⚠️ مقبول"
        strength_level = "MODERATE"
    else:
        strength       = "❌ ضعيف"
        strength_level = "WEAK"
        send_signal    = False

    emoji = "🟢" if direction == "BUY" else ("🔴" if direction == "SELL" else "🟡")

    print(f"\n  📋 الحكم: {emoji} {direction} | ثقة: {confidence}% | أصوات: {vote_count}/5")
    print(f"  {'✅ إشارة تُرسل' if send_signal else '⏭️ لا إشارة'}")

    return {
        "send_signal"      : send_signal,
        "direction"        : direction,
        "emoji"            : emoji,
        "votes"            : f"{vote_count}/5",
        "strength"         : strength,
        "strength_level"   : strength_level,
        "avg_confidence"   : confidence,
        "winning_argument" : verdict.get("winning_argument", ""),
        "dissent_summary"  : verdict.get("dissent_summary"),
        "judge_reasoning"  : verdict.get("judge_reasoning", ""),
        "mind_changes"     : verdict.get("mind_changes", 0),
        "raw_votes"        : verdict.get("raw_votes", {}),
        "openings"         : openings,
        "debates"          : debates,
        # للتوافق مع باقي النظام
        "consensus"        : send_signal,
        "consensus_agents" : [
            {"agent_name": v["name"],
             "reason"    : v["analysis"][:100]}
            for v in openings.values()
            if v["stance"] == direction
        ],
        "dissenters"       : [
            {"agent_name": v["name"],
             "vote"      : v["final_stance"],
             "reason"    : v["debate_reply"][:80]}
            for v in debates.values()
            if v["final_stance"] != direction
        ],
    }
