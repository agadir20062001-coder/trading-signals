"""
الوكلاء الخمسة — كل وكيل يصوت باستقلالية تامة
نظام الإجماع: 4/5 أو 5/5 فقط يُنتج إشارة
"""

import json
import os
from dotenv import load_dotenv

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
            temperature=0.1,
            max_tokens=1024
        )
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            temperature=0.1
        )

# ============================================================
# تعريف الوكلاء الخمسة
# ============================================================
AGENT_DEFINITIONS = {

    "technical": {
        "name"  : "المحلل التقني 📊",
        "focus" : "التحليل التقني",
        "prompt": """
أنت محلل تقني خبير ومتخصص فقط في المؤشرات التقنية.
مهمتك: تحليل البيانات التقنية وإصدار صوت واحد فقط.

ركّز حصراً على:
- المتوسطات المتحركة (MA20, MA50, MA200)
- RSI (تشبع شراء >70، تشبع بيع <30)
- MACD (الاتجاه، التقاطع، الهيستوغرام)
- Bollinger Bands (موقع السعر)
- حجم التداول (تأكيد الحركة)
- نظام التقلب (Low/Normal/High)

قاعدة صارمة: أجب بـ JSON فقط، لا كلام إضافي.
{
  "vote": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "reason": "جملة واحدة موجزة"
}
"""
    },

    "news": {
        "name"  : "محلل الأخبار 📰",
        "focus" : "تحليل الأخبار والأحداث",
        "prompt": """
أنت محلل أخبار مالي متخصص فقط في تأثير الأحداث على الأسعار.
مهمتك: تقييم الأخبار الأخيرة وإصدار صوت واحد فقط.

ركّز حصراً على:
- أخبار الشركة أو الأصل الأخيرة
- إعلانات الأرباح والتوقعات
- الأحداث التنظيمية والسياسية
- أخبار القطاع والمنافسين
- تأثير الأخبار على المدى القصير

قاعدة صارمة: أجب بـ JSON فقط، لا كلام إضافي.
{
  "vote": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "reason": "جملة واحدة موجزة"
}
"""
    },

    "sentiment": {
        "name"  : "محلل المشاعر 💬",
        "focus" : "مشاعر السوق",
        "prompt": """
أنت محلل متخصص في قياس مشاعر السوق والمتداولين.
مهمتك: تقييم حالة المشاعر وإصدار صوت واحد فقط.

ركّز حصراً على:
- اتجاه السوق العام (Risk-on / Risk-off)
- مستوى الخوف والجشع
- حجم التداول كمؤشر للاهتمام
- الزخم السعري قصير المدى
- تغيرات الـ 24 ساعة الأخيرة

قاعدة صارمة: أجب بـ JSON فقط، لا كلام إضافي.
{
  "vote": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "reason": "جملة واحدة موجزة"
}
"""
    },

    "fundamentals": {
        "name"  : "محلل الأساسيات 📈",
        "focus" : "التحليل الأساسي",
        "prompt": """
أنت محلل أساسيات مالية متخصص في القيمة الجوهرية للأصول.
مهمتك: تقييم القيمة الحقيقية وإصدار صوت واحد فقط.

ركّز حصراً على:
- للأسهم: PE, EPS, نمو الإيرادات, القطاع
- للكريبتو: حالة الشبكة, التبني, حجم المعاملات
- للفوركس: الفوارق الاقتصادية بين الدولتين
- للسلع: العرض والطلب الأساسي
- السعر مقارنة بالقيمة العادلة

قاعدة صارمة: أجب بـ JSON فقط، لا كلام إضافي.
{
  "vote": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "reason": "جملة واحدة موجزة"
}
"""
    },

    "macro": {
        "name"  : "محلل الاقتصاد الكلي 🌍",
        "focus" : "الاقتصاد الكلي",
        "prompt": """
أنت محلل اقتصاد كلي متخصص في تأثير العوامل الاقتصادية الكبرى.
مهمتك: تقييم البيئة الاقتصادية وإصدار صوت واحد فقط.

ركّز حصراً على:
- أسعار الفائدة وسياسة الفيدرالي
- معدلات التضخم والبطالة
- الدولة القوية في الفوركس
- تأثير الاقتصاد الكلي على الأصل
- المرحلة الاقتصادية (توسع/انكماش)

قاعدة صارمة: أجب بـ JSON فقط، لا كلام إضافي.
{
  "vote": "BUY أو SELL أو HOLD",
  "confidence": رقم من 0 إلى 100,
  "reason": "جملة واحدة موجزة"
}
"""
    }
}


# ============================================================
# تشغيل الوكيل وجمع صوته
# ============================================================
def run_agent(agent_key: str, symbol: str, market_data: dict,
              macro_data: dict, mtf: dict = None) -> dict:
    llm    = get_llm()
    agent  = AGENT_DEFINITIONS[agent_key]
    ind    = market_data.get("indicators", {})
    adx    = ind.get("adx", {})
    sr     = ind.get("sr", {})
    pat    = ind.get("patterns", {})

    # بيانات الأطر الزمنية
    mtf_text = "غير متاح"
    if mtf and mtf.get("available"):
        tfs = mtf.get("timeframes", {})
        mtf_text = (
            f"1H: {tfs.get('1H', {}).get('trend','N/A')} (RSI={tfs.get('1H',{}).get('rsi','N/A')})\n"
            f"   4H: {tfs.get('4H', {}).get('trend','N/A')} (RSI={tfs.get('4H',{}).get('rsi','N/A')})\n"
            f"   1D: {tfs.get('1D', {}).get('trend','N/A')} (RSI={tfs.get('1D',{}).get('rsi','N/A')})\n"
            f"   التوافق: {mtf.get('alignment','N/A')}"
        )

    user_message = f"""
الأصل: {symbol}
النوع: {market_data.get('type', 'unknown')}
السعر الحالي: {market_data.get('price', 'N/A')}
التغير 24 ساعة: {market_data.get('change_24h', 'N/A')}%

البيانات التقنية (الإطار 1H):
- MA20: {ind.get('ma20','N/A')} | MA50: {ind.get('ma50','N/A')} | MA200: {ind.get('ma200','N/A')}
- RSI: {ind.get('rsi','N/A')}
- MACD Hist: {ind.get('macd_hist','N/A')}
- Bollinger %: {ind.get('bb_pct','N/A')}
- حجم نسبي: {ind.get('vol_ratio','N/A')}x
- نظام التقلب: {ind.get('regime','N/A')}

تعدد الأطر الزمنية:
   {mtf_text}

قوة الاتجاه (ADX):
- ADX: {adx.get('adx','N/A')} — {adx.get('strength','N/A')}
- الاتجاه: {adx.get('direction','N/A')}
- قابل للتداول: {'نعم' if adx.get('tradeable', True) else 'لا — سوق عرضي'}

الدعم والمقاومة:
- أقرب دعم: {sr.get('nearest_support','N/A')} (بُعد: {sr.get('dist_to_support','N/A')}%)
- أقرب مقاومة: {sr.get('nearest_resistance','N/A')} (بُعد: {sr.get('dist_to_resistance','N/A')}%)
- الوضع: {sr.get('context','N/A')}

الأنماط الفنية المكتشفة ({pat.get('count',0)} نمط):
{chr(10).join('- ' + p for p in pat.get('detected',[])) or '- لا أنماط واضحة'}
الانحياز الكلي: {pat.get('summary','N/A')}

البيانات الأساسية:
- القطاع: {market_data.get('sector','N/A')}
- P/E: {market_data.get('pe_ratio','N/A')} | EPS: {market_data.get('eps','N/A')}

الاقتصاد الكلي:
- سعر الفائدة: {macro_data.get('fed_rate','N/A')}%
- التضخم: {macro_data.get('inflation','N/A')}
- البطالة: {macro_data.get('unemployment','N/A')}%

صوّت الآن بناءً على تخصصك فقط: {agent['focus']}
"""

    try:
        response = llm.invoke([
            {"role": "system", "content": agent["prompt"]},
            {"role": "user",   "content": user_message}
        ])

        content = response.content.strip()
        # تنظيف JSON
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)
        result["agent_name"] = agent["name"]
        result["agent_key"]  = agent_key
        return result

    except Exception as e:
        return {
            "vote"      : "HOLD",
            "confidence": 0,
            "reason"    : f"خطأ: {str(e)[:50]}",
            "agent_name": agent["name"],
            "agent_key" : agent_key
        }


# ============================================================
# جمع أصوات جميع الوكلاء الخمسة
# ============================================================
def collect_all_votes(symbol: str, market_data: dict,
                      macro_data: dict, mtf: dict = None) -> dict:
    print(f"\n🗳️ جمع الأصوات لـ {symbol}...")
    votes = {}

    for agent_key in AGENT_DEFINITIONS:
        agent_name = AGENT_DEFINITIONS[agent_key]["name"]
        print(f"   ⏳ {agent_name}...")
        votes[agent_key] = run_agent(agent_key, symbol, market_data, macro_data, mtf)
        print(f"   ✅ صوّت بـ: {votes[agent_key]['vote']} ({votes[agent_key]['confidence']}%)")

    return votes
