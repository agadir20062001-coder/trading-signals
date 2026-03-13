"""
محرك الإجماع — قلب النظام
لا إشارة تخرج إلا بموافقة 4/5 أو 5/5
"""

import os
from dotenv import load_dotenv

load_dotenv()

CONSENSUS_THRESHOLD = int(os.getenv("CONSENSUS_THRESHOLD", "4"))


def run_consensus(votes: dict) -> dict:
    """
    يطبق نظام الإجماع على أصوات الوكلاء الخمسة
    يُعيد نتيجة كاملة مع قرار الإرسال
    """

    # ============================================================
    # تجميع الأصوات
    # ============================================================
    tally = {"BUY": [], "SELL": [], "HOLD": []}

    for agent_key, result in votes.items():
        direction = result.get("vote", "HOLD").upper()
        if direction not in tally:
            direction = "HOLD"
        tally[direction].append({
            "agent_key" : agent_key,
            "agent_name": result.get("agent_name", agent_key),
            "confidence": result.get("confidence", 0),
            "reason"    : result.get("reason", "")
        })

    # ============================================================
    # إيجاد أعلى اتجاه
    # ============================================================
    consensus_direction = max(tally, key=lambda x: len(tally[x]))
    consensus_count     = len(tally[consensus_direction])
    consensus_agents    = tally[consensus_direction]

    # ============================================================
    # هل تحقق الإجماع؟
    # ============================================================
    if consensus_count < CONSENSUS_THRESHOLD:
        return {
            "send_signal"  : False,
            "consensus"    : False,
            "direction"    : None,
            "votes_detail" : tally,
            "reason"       : (
                f"لا إجماع — "
                f"BUY:{len(tally['BUY'])} "
                f"SELL:{len(tally['SELL'])} "
                f"HOLD:{len(tally['HOLD'])}"
            )
        }

    # ============================================================
    # حساب مقاييس الإجماع
    # ============================================================
    avg_confidence = sum(
        a["confidence"] for a in consensus_agents
    ) / consensus_count

    min_confidence = min(a["confidence"] for a in consensus_agents)
    max_confidence = max(a["confidence"] for a in consensus_agents)

    # قوة الإجماع
    if consensus_count == 5:
        if avg_confidence >= 80:
            strength       = "🔥 استثنائي"
            strength_level = "EXCEPTIONAL"
        else:
            strength       = "💪 قوي جداً"
            strength_level = "VERY_STRONG"
    else:  # 4/5
        if avg_confidence >= 70:
            strength       = "✅ قوي"
            strength_level = "STRONG"
        else:
            strength       = "⚠️ مقبول"
            strength_level = "MODERATE"

    # ============================================================
    # المعارضون (إن وجدوا)
    # ============================================================
    dissenters = []
    for direction, agents in tally.items():
        if direction != consensus_direction:
            for agent in agents:
                dissenters.append({
                    "agent_name": agent["agent_name"],
                    "vote"      : direction,
                    "reason"    : agent["reason"]
                })

    # ============================================================
    # الإيموجي بناءً على القرار
    # ============================================================
    if consensus_direction == "BUY":
        emoji = "🟢"
    elif consensus_direction == "SELL":
        emoji = "🔴"
    else:
        emoji = "🟡"

    return {
        "send_signal"    : True,
        "consensus"      : True,
        "direction"      : consensus_direction,
        "emoji"          : emoji,
        "votes"          : f"{consensus_count}/5",
        "strength"       : strength,
        "strength_level" : strength_level,
        "avg_confidence" : round(avg_confidence, 1),
        "min_confidence" : min_confidence,
        "max_confidence" : max_confidence,
        "consensus_agents": consensus_agents,
        "dissenters"     : dissenters,
        "votes_detail"   : tally
    }
