"""
نظام الإشعارات بالبريد الإلكتروني
يرسل تقريراً مفصلاً كاملاً عند كل إشارة
يدعم: Gmail / Outlook / أي SMTP
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from datetime             import datetime
import pytz
from dotenv               import load_dotenv

load_dotenv()


# ============================================================
# إعداد الإيميل
# ============================================================
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASS = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO   = os.getenv("EMAIL_TO", "")


def is_email_configured() -> bool:
    return bool(EMAIL_FROM and EMAIL_PASS and EMAIL_TO)


# ============================================================
# بناء محتوى الإيميل HTML
# ============================================================
def _build_html(symbol, consensus, risk, market_data,
                liquidity, entry_exit) -> str:

    ind       = market_data.get("indicators", {})
    adx       = ind.get("adx", {})
    sr        = ind.get("sr",  {})
    pat       = ind.get("patterns", {})
    candles   = ind.get("candles", {})
    chart_pat = ind.get("chart",   {})
    stoch     = ind.get("stoch",   {})
    conf_15m  = consensus.get("confirmation_15m", {})
    openings  = consensus.get("openings", {})
    debates   = consensus.get("debates",  {})
    ee        = entry_exit or {}
    day       = ee.get("day",   {})
    swing     = ee.get("swing", {})
    entry     = ee.get("entry", {})

    direction = consensus.get("direction", "HOLD")
    color     = "#27ae60" if direction == "BUY" else \
                "#e74c3c" if direction == "SELL" else "#f39c12"
    now_utc   = datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ---- تقارير الوكلاء ----
    agents_html = ""
    for key, op in openings.items():
        db     = debates.get(key, {})
        struct = op.get("structured", {})
        s_icon = "🟢" if op["stance"] == "BUY" else \
                 "🔴" if op["stance"] == "SELL" else "🟡"
        f_icon = "🟢" if db.get("final_stance","") == "BUY" else \
                 "🔴" if db.get("final_stance","") == "SELL" else "🟡"
        changed = "🔄 غيّر رأيه" if db.get("changed_mind") else ""

        agents_html += f"""
        <div style="background:#f8f9fa;border-right:4px solid {color};
                    padding:12px;margin:8px 0;border-radius:4px;">
          <b>{op['name']}</b>
          <div style="margin:6px 0;font-size:13px;">
            <b>الجولة 1:</b> {s_icon} {op['stance']}<br>
            <span style="color:#555;">{op.get('analysis','')}</span>
          </div>
          <div style="margin:6px 0;font-size:13px;">
            <b>الجولة 2:</b> {f_icon} {db.get('final_stance','')}
            <span style="color:#e74c3c;font-weight:bold;"> {changed}</span><br>
            <span style="color:#555;">{db.get('debate_reply','')}</span>
          </div>
        </div>"""

    # ---- الأنماط الفنية ----
    all_patterns = (
        candles.get("detected", []) +
        chart_pat.get("detected", [])
    )
    pat_html = "".join(
        f'<span style="background:#eee;padding:2px 6px;margin:2px;'
        f'border-radius:3px;font-size:12px;">{p}</span>'
        for p in all_patterns
    ) or "<span style='color:#999;'>لا أنماط</span>"

    # ---- تأكيد 15M ----
    conf_color = "#27ae60" if conf_15m.get("status") == "confirmed" else \
                 "#e74c3c" if conf_15m.get("status") == "conflicting" else "#f39c12"
    conf_html  = f"""
        <tr>
          <td colspan="2" style="color:{conf_color};font-weight:bold;">
            ⏱️ تأكيد 15M: {conf_15m.get('label','غير متاح')}
            {'(' + ('+' if conf_15m.get('confidence_delta',0)>=0 else '') +
             str(conf_15m.get('confidence_delta',0)) + '%)'
             if conf_15m.get('available') else ''}
          </td>
        </tr>""" if conf_15m else ""

    return f"""
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; background: #f5f5f5;
         margin:0; padding:20px; color:#333; }}
  .card {{ background:#fff; border-radius:8px; padding:20px;
           margin:0 auto; max-width:700px;
           box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
  h2 {{ color:{color}; margin:0 0 4px 0; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:6px 8px; font-size:14px; }}
  tr:nth-child(even) {{ background:#f9f9f9; }}
  .section {{ margin:16px 0; }}
  .section-title {{ font-weight:bold; font-size:15px;
                    border-bottom:2px solid {color};
                    padding-bottom:4px; margin-bottom:10px; }}
  .verdict {{ background:{color}; color:#fff; padding:12px 16px;
              border-radius:6px; margin:12px 0; }}
</style>
</head>
<body>
<div class="card">

  <!-- العنوان -->
  <h2>{'🟢' if direction=='BUY' else '🔴' if direction=='SELL' else '🟡'}
      إشارة {direction} — {symbol}</h2>
  <p style="color:#666;margin:0 0 16px 0;">{now_utc}</p>

  <!-- ملخص القرار -->
  <div class="verdict">
    <b>الحكم: {consensus.get('votes','N/A')} — {consensus.get('strength','')}</b><br>
    الثقة: {consensus.get('avg_confidence','N/A')}%<br>
    حكم القاضي: {consensus.get('judge_reasoning','')}<br>
    الحجة الفاصلة: {consensus.get('winning_argument','')}
  </div>

  <!-- السعر والتغير -->
  <div class="section">
    <div class="section-title">📊 ملخص السوق</div>
    <table>
      <tr><td><b>السعر</b></td><td>{market_data.get('price','N/A')}</td>
          <td><b>التغير 24h</b></td>
          <td>{market_data.get('change_24h',0):+.2f}%</td></tr>
      {conf_html}
    </table>
  </div>

  <!-- مناطق الدخول والخروج -->
  {'<div class="section"><div class="section-title">🎯 مناطق الدخول والخروج</div>' +
   f'<table><tr><td><b>منطقة الدخول</b></td><td>{entry.get("zone","N/A")}</td></tr>' +
   f'<tr style="background:#e8f5e9"><td><b>يومي — وقف الخسارة</b></td><td>{day.get("sl","N/A")}</td>' +
   f'<td><b>R/R</b></td><td>{day.get("rr","N/A")}</td></tr>' +
   f'<tr><td><b>يومي — TP1</b></td><td>{day.get("tp1","N/A")}</td>' +
   f'<td><b>TP2</b></td><td>{day.get("tp2","N/A")}</td></tr>' +
   f'<tr style="background:#e8f5e9"><td><b>سوينغ — وقف الخسارة</b></td><td>{swing.get("sl","N/A")}</td>' +
   f'<td><b>R/R</b></td><td>{swing.get("rr","N/A")}</td></tr>' +
   f'<tr><td><b>سوينغ — TP1</b></td><td>{swing.get("tp1","N/A")}</td>' +
   f'<td><b>TP2</b></td><td>{swing.get("tp2","N/A")}</td>' +
   f'<td><b>TP3</b></td><td>{swing.get("tp3","N/A")}</td></tr>' +
   '</table></div>' if ee.get("available") else ""}

  <!-- المؤشرات التقنية -->
  <div class="section">
    <div class="section-title">📈 المؤشرات التقنية</div>
    <table>
      <tr><td><b>RSI</b></td><td>{ind.get('rsi','N/A')}</td>
          <td><b>MACD</b></td><td>{ind.get('macd_hist','N/A')}</td>
          <td><b>BB%</b></td><td>{ind.get('bb_pct','N/A')}</td></tr>
      <tr><td><b>MA20</b></td><td>{ind.get('ma20','N/A')}</td>
          <td><b>MA50</b></td><td>{ind.get('ma50','N/A')}</td>
          <td><b>MA200</b></td><td>{ind.get('ma200','N/A')}</td></tr>
      <tr><td><b>ADX</b></td>
          <td colspan="5">{adx.get('adx','N/A')} — {adx.get('strength','N/A')} | {adx.get('direction','N/A')}</td></tr>
      <tr><td><b>Stochastic</b></td>
          <td colspan="5">K={stoch.get('k','N/A')} | D={stoch.get('d','N/A')} — {stoch.get('signal','N/A')}</td></tr>
      <tr><td><b>دعم</b></td><td>{sr.get('nearest_support','N/A')}</td>
          <td><b>مقاومة</b></td><td>{sr.get('nearest_resistance','N/A')}</td>
          <td colspan="2" style="color:#666;font-size:12px;">{sr.get('context','')}</td></tr>
      <tr><td><b>ATR</b></td><td>{ind.get('atr_pct','N/A')}%</td>
          <td><b>حجم</b></td><td>{ind.get('vol_ratio','N/A')}x</td>
          <td><b>تقلب</b></td><td>{ind.get('regime','N/A')}</td></tr>
    </table>
  </div>

  <!-- الأنماط الفنية -->
  <div class="section">
    <div class="section-title">🕯️ الأنماط الفنية</div>
    <div style="padding:8px 0;">{pat_html}</div>
    <div style="margin-top:6px;font-size:13px;color:#555;">
      شمعية: {candles.get('summary','N/A')} |
      مخططية: {chart_pat.get('summary','N/A')}
    </div>
  </div>

  <!-- إدارة المخاطر -->
  <div class="section">
    <div class="section-title">🛡️ إدارة المخاطر</div>
    <table>
      <tr><td><b>VaR 95%</b></td><td>{risk.get('var_95','N/A')}%</td>
          <td><b>CVaR 95%</b></td><td>{risk.get('cvar_95','N/A')}%</td></tr>
      <tr><td><b>Kelly Size</b></td><td>{risk.get('kelly_size','N/A')}%</td>
          <td><b>مستوى المخاطرة</b></td><td>{risk.get('risk_label','N/A')}</td></tr>
    </table>
  </div>

  <!-- تقارير الوكلاء الكاملة -->
  <div class="section">
    <div class="section-title">🤖 النقاش الكامل بين الوكلاء</div>
    {agents_html}
  </div>

  <!-- تذييل -->
  <div style="margin-top:20px;padding-top:12px;border-top:1px solid #eee;
              font-size:12px;color:#999;text-align:center;">
    نظام الإشارات الموحد v7 | {now_utc}<br>
    ⚠️ للتحليل والتعلم فقط — ليس توصية استثمارية
  </div>

</div>
</body>
</html>"""


# ============================================================
# إرسال الإيميل
# ============================================================
def send_email_report(symbol: str, consensus: dict, risk: dict,
                      market_data: dict, liquidity: dict = None,
                      entry_exit: dict = None) -> bool:
    """
    يرسل تقريراً مفصلاً بالبريد الإلكتروني
    يُعيد True عند النجاح أو False عند الفشل
    """
    if not is_email_configured():
        print("   📧 الإيميل غير مُعدّ — تخطي")
        return False

    try:
        direction = consensus.get("direction", "HOLD")
        strength  = consensus.get("strength", "")
        confidence= consensus.get("avg_confidence", 0)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"{'🟢' if direction=='BUY' else '🔴'} "
            f"إشارة {direction} — {symbol} | "
            f"{consensus.get('votes','N/A')} | "
            f"ثقة {confidence}%"
        )
        msg["From"] = EMAIL_FROM
        msg["To"]   = EMAIL_TO

        html = _build_html(symbol, consensus, risk,
                           market_data, liquidity, entry_exit)
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

        print(f"   📧 إيميل أُرسل: {symbol} {direction}")
        return True

    except Exception as e:
        print(f"   📧 فشل إرسال الإيميل: {e}")
        return False
