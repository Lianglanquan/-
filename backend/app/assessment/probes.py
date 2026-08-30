"""Warm, bounded participant-facing adaptive probe protocol.

The probe is a presentation contract, not a hidden scoring rubric.  Option
labels describe possible meanings in ordinary language and never encode a
0/1/2 value or a clinical conclusion.  The participant may always write their
own words or pause.
"""

from __future__ import annotations

import re
from typing import Any


PROBE_PROTOCOL_VERSION = "cat-companion-probe-v1"

_FORBIDDEN_COMPANION_LANGUAGE = re.compile(
    r"(?:[012]\s*分|风险|诊断|高风险|低风险|自杀|不想活|结束生命|伤害自己)",
    flags=re.IGNORECASE,
)


_PACKS: dict[str, list[dict[str, str]]] = {
    "Q01": [
        {"id": "settled", "label": "更像平静、慢慢安静下来"},
        {"id": "low", "label": "更像低落、往下沉一些"},
        {"id": "tense", "label": "更像紧绷、心里悬着"},
    ],
    "Q02": [
        {"id": "connected", "label": "我更像是融在其中"},
        {"id": "apart", "label": "我更像是站在外面"},
        {"id": "shifting", "label": "两种感觉会来回变化"},
    ],
    "Q03": [
        {"id": "held", "label": "我会感到被他们放在心上"},
        {"id": "burdened", "label": "我也会觉得让他们辛苦了"},
        {"id": "mixed", "label": "感激和难受会一起出现"},
    ],
    "Q04": [
        {"id": "closer", "label": "关系会更靠近一些"},
        {"id": "steady", "label": "关系大致保持原样"},
        {"id": "apart", "label": "关系可能拉开一点"},
    ],
    "Q05": [
        {"id": "closer", "label": "我会期待他们继续靠近我"},
        {"id": "leave", "label": "我会担心他们慢慢离开"},
        {"id": "uncertain", "label": "我很难预先知道会怎样"},
    ],
    "Q06": [
        {"id": "reach_out", "label": "我会找一个人说说"},
        {"id": "handle_alone", "label": "我通常还是自己扛着"},
        {"id": "depends", "label": "要看事情和当时的状态"},
    ],
    "Q07": [
        {"id": "easy", "label": "对我来说比较容易"},
        {"id": "hard", "label": "我需要很大力气才能说"},
        {"id": "depends", "label": "有时可以，有时很困难"},
    ],
    "Q08": [
        {"id": "event_only", "label": "我主要是在说这件事本身"},
        {"id": "self_too", "label": "我也会想到是不是自己不够好"},
        {"id": "mixed", "label": "两边都会想到一些"},
    ],
    "Q09": [
        {"id": "event_only", "label": "我只是在说这件事没做好"},
        {"id": "whole_self", "label": "我会连自己也一起否定"},
        {"id": "depends", "label": "要看当时有多糟"},
    ],
    "Q10": [
        {"id": "specific", "label": "我只是在比较这件事"},
        {"id": "self_value", "label": "我会想到自己的整体价值"},
        {"id": "mixed", "label": "两种想法都会有"},
    ],
    "Q11": [
        {"id": "continue", "label": "我会再试试或换个办法"},
        {"id": "pause", "label": "我会先停一停，等自己缓下来"},
        {"id": "give_up", "label": "我常常就不再继续了"},
    ],
    "Q12": [
        {"id": "seek_way", "label": "我会过一会儿再找办法"},
        {"id": "leave_it", "label": "我会先把它放下"},
        {"id": "stuck", "label": "我常常会卡在那里"},
    ],
    "Q13": [
        {"id": "regain_attention", "label": "我能把注意力带回别处"},
        {"id": "carried_away", "label": "它还是会把我带走"},
        {"id": "both", "label": "有时能做到，有时做不到"},
    ],
    "Q14": [
        {"id": "their_state", "label": "我会先想到对方当下的状态"},
        {"id": "relationship", "label": "我会想到关系是不是出了问题"},
        {"id": "my_fault", "label": "我会先怀疑是不是自己的问题"},
    ],
    "Q15": [
        {"id": "act", "label": "我会先处理还能处理的部分"},
        {"id": "wait", "label": "我会先等一等，不急着做什么"},
        {"id": "stop", "label": "我会觉得做什么都没有用"},
    ],
    "Q16": [
        {"id": "support", "label": "它更像一份把我和别人连在一起的牵挂"},
        {"id": "burden", "label": "它更像一份让我感到压力的牵挂"},
        {"id": "mixed", "label": "这两种感觉会一起出现"},
    ],
    "Q17": [
        {"id": "concrete_future", "label": "我能想到一个具体的生活画面"},
        {"id": "blank_future", "label": "我脑子里还是很空"},
        {"id": "uncertain_future", "label": "有一点画面，但还不确定"},
    ],
    "Q18": [
        {"id": "protect", "label": "我会先保护自己和身边的人"},
        {"id": "freeze", "label": "我可能会先愣住或不知所措"},
        {"id": "call_help", "label": "我会先找人或寻找帮助"},
    ],
    "Q19": [
        {"id": "fear", "label": "最先冒出来的是害怕"},
        {"id": "attachment", "label": "最先想到的是舍不得"},
        {"id": "blank", "label": "最先出现的可能是一片空白"},
    ],
    "Q20": [
        {"id": "low_impact", "label": "我能想到一个比较轻的程度"},
        {"id": "high_impact", "label": "我能想到一个很重的程度"},
        {"id": "no_number", "label": "我还没有一个数字，想先说说影响在哪里"},
    ],
}


def _quote(response: str) -> str:
    value = " ".join(str(response or "").split())
    if len(value) > 32:
        value = value[:32] + "…"
    return value or "刚才那句话"


def _gap_sentence(target_gap: str | None, question_id: str) -> str:
    gap = str(target_gap or "")
    if question_id == "Q16":
        return "它听起来很有分量，只是我还不确定，这份分量是在托住你，还是也让你有些累。"
    if "方向" in gap or "正负" in gap:
        return "我听见了一个方向，只是它还没有完全显出是靠近、远离，还是两种感觉一起在。"
    if "对象" in gap or "谁" in gap:
        return "我好像听见了一点感受，但还不知道它指向谁，或指向哪一件事。"
    if "程度" in gap or "强度" in gap:
        return "我听见这件事有影响，只是还不知道它在你心里有多重。"
    if "时间" in gap or "持续" in gap:
        return "我想再靠近一点，看看这种感受是在某个时刻出现，还是一直跟着你。"
    if "行为" in gap or "行动" in gap or "做法" in gap:
        return "我听见了一个念头，还想知道它真正出现时，你通常会怎么做。"
    return "我已经听见一点方向，只是还不想替你把它说死。"


def _reflection_sentence(probe_type: str, response: str) -> str:
    quoted = _quote(response)
    if probe_type == "CONFIRMATION":
        return f"我回头又听了听“{quoted}”，想和你对照一下。"
    if probe_type == "DISAMBIGUATION":
        return f"我把“{quoted}”轻轻放在这里，先不急着替它选方向。"
    return f"“{quoted}”我收到了，想和你再靠近一点点。"


def _invitation_sentence(probe_type: str) -> str:
    if probe_type == "CONFIRMATION":
        return "你可以确认它仍然靠近原来的感觉，也可以把我带去另一边。"
    if probe_type == "DISAMBIGUATION":
        return "你可以选一条比较靠近的路，也可以写下自己的那一条。"
    return "不用急着说完整；有哪一小部分想先告诉我吗？"


def _default_options(question_id: str) -> list[dict[str, str]]:
    options = [dict(option) for option in _PACKS.get(question_id, [])]
    options.extend([
        {"id": "other", "label": "都不太像，我想自己说"},
        {"id": "not_ready", "label": "今天先放在这里"},
    ])
    return options


def _valid_ai_options(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            continue
        option_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(value.get("id", "")))[:40]
        label = " ".join(str(value.get("label", "")).split())[:120]
        # These two ids are reserved for the protocol's guaranteed exits;
        # custom AI text must not change their meaning.
        if option_id in {"other", "not_ready"}:
            continue
        if not option_id or not label or option_id in seen or _FORBIDDEN_COMPANION_LANGUAGE.search(label):
            continue
        seen.add(option_id)
        result.append({"id": option_id, "label": label})
    # One isolated AI option is not a meaningful semantic fork. Fall back to
    # the item-specific neutral pack unless at least two paths survived.
    return result[:5] if len(result) >= 2 else []


def _companion_text(value: Any, fallback: str, limit: int) -> str:
    """Keep model-authored cat copy warm and free of scoring/risk language."""

    text = " ".join(str(value or "").split())[:limit]
    if not text or _FORBIDDEN_COMPANION_LANGUAGE.search(text):
        return fallback
    return text


def normalise_cat_probe(raw: Any, *, question_id: str, probe_type: str, target_gap: str | None, response: str = "") -> dict[str, Any] | None:
    """Validate AI-provided companion language and add mandatory exits."""

    if probe_type not in {"CLARIFICATION", "DISAMBIGUATION", "CONFIRMATION"}:
        return None
    value = raw if isinstance(raw, dict) else {}
    options = _valid_ai_options(value.get("options")) or _default_options(question_id)
    ids = {option["id"] for option in options}
    if "other" not in ids:
        options.append({"id": "other", "label": "都不太像，我想自己说"})
    if "not_ready" not in ids:
        options.append({"id": "not_ready", "label": "今天先放在这里"})
    gap = str(value.get("target_gap") or target_gap or "方向还没有完全显出来")[:240]
    return {
        "version": PROBE_PROTOCOL_VERSION,
        "probe_id": f"{question_id}:{probe_type.lower()}:v1",
        "probe_type": probe_type,
        "target_gap": gap,
        "cat_reflection": _companion_text(value.get("cat_reflection"), _reflection_sentence(probe_type, response), 240),
        "cat_tentative_understanding": _companion_text(value.get("cat_tentative_understanding"), _gap_sentence(gap, question_id), 360),
        "cat_humility": _companion_text(value.get("cat_humility"), "也可能是我听偏了；如果是这样，随时把我带回你的意思。", 120),
        "cat_invitation": _companion_text(value.get("cat_invitation"), _invitation_sentence(probe_type), 120),
        "options": options,
        "free_text_label": _companion_text(value.get("free_text_label"), "都不太像，我想自己说", 100),
        "pause_label": _companion_text(value.get("pause_label"), "今天先放在这里", 100),
        "response_optional": True,
    }


def default_cat_probe(*, question_id: str, probe_type: str, target_gap: str | None, response: str = "") -> dict[str, Any] | None:
    return normalise_cat_probe(None, question_id=question_id, probe_type=probe_type, target_gap=target_gap, response=response)
