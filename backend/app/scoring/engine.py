"""Auditable rubric-guided scoring baseline.

This implementation is deliberately deterministic so research comparisons can
start before a provider-backed LLM is configured. It is not a clinical risk
classifier and never turns a score into a safety conclusion.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    text: str
    start: int
    end: int
    rule: str


class ProbeOption(BaseModel):
    id: str
    label: str


class CatProbe(BaseModel):
    version: str
    probe_id: str
    probe_type: str
    target_gap: str
    cat_reflection: str
    cat_tentative_understanding: str
    cat_humility: str
    cat_invitation: str
    options: list[ProbeOption]
    free_text_label: str
    pause_label: str
    response_optional: bool = True


class ScoreResult(BaseModel):
    question_id: str
    response: str
    preliminary_score: int = Field(ge=0, le=2)
    score_status: str
    evidence_sufficiency: str
    rationale: str
    evidence_spans: list[Evidence]
    confidence: float = Field(ge=0, le=1)
    target_gap: str | None = None
    clarification_question: str | None = None
    safety_state: str = "CLEAR"
    rubric_version: str
    decision_reasons: list[str] = Field(default_factory=list)
    review_recommended: bool = False
    model_margin: float | None = None
    clarification_round: int = 0
    probe_type: str | None = None
    cat_probe: CatProbe | None = None


AMBIGUOUS = ("不知道", "不清楚", "随缘", "还行", "责任", "担心", "无所谓", "说不清", "没想法")
HIGH = ("绝望", "解脱", "负担", "废物", "没用", "等待死亡", "结束一切", "不想活", "自杀")
MID = ("焦虑", "恐惧", "害怕", "难过", "孤单", "失望", "烦躁", "困难", "放弃", "拖延", "麻木")

GAP_PROBES: dict[str, tuple[str, str]] = {
    "Q01": ("情绪的方向或强度还不明确", "这种感受更接近平静、低落、紧张，还是其他状态？"),
    "Q02": ("你在群体中的主观感受还不明确", "当时你更像是融入其中、保持距离，还是有别的感受？"),
    "Q03": ("你如何理解他人的付出还不明确", "看到这些付出时，你最直接的感受或想做的事情是什么？"),
    "Q04": ("袒露之后预期发生什么还不明确", "你更担心或期待袒露之后发生什么？"),
    "Q05": ("你预期亲近的人会怎样回应还不明确", "你觉得他们更可能靠近、保持不变，还是离开？"),
    "Q06": ("求助的对象或方式还不明确", "遇到麻烦时，你通常会向谁、或通过什么方式求助？"),
    "Q07": ("倾诉对你意味着容易还是困难还不明确", "这件事对你来说更容易、勉强可以，还是很困难？"),
    "Q08": ("你对未达预期的评价还不明确", "那一刻你主要是在评价这件事，还是在评价自己？"),
    "Q09": ("评价针对事件还是整个自我还不明确", "你指的是这件事没做好，还是觉得自己整体都不行？"),
    "Q10": ("比较之后对自己的判断范围还不明确", "这种想法只针对这件事，还是会扩展到对自己的整体评价？"),
    "Q11": ("挫败后的具体应对还不明确", "接下来你通常会继续尝试、暂停调整，还是放弃？"),
    "Q12": ("暂时解决不了时的后续行动还不明确", "你通常会先放一放并再想办法，还是不再处理？"),
    "Q13": ("你与消极想法之间的关系还不明确", "这种做法会让你重新掌握注意力，还是仍被想法牵着走？"),
    "Q14": ("你把对方冷淡归因于什么还不明确", "你更倾向认为是对方当下的状态、关系问题，还是自己的问题？"),
    "Q15": ("失去掌控时的行动倾向还不明确", "这种想法之后，你通常会处理能处理的部分，还是不再行动？"),
    "Q16": ("牵挂的正负方向还不明确", "牵挂对你更像支持、负担，还是两者都有？"),
    "Q17": ("未来画面的内容和方向还不明确", "你想到的画面里，自己大概在哪里、在做什么？"),
    "Q18": ("危险中的求生行动或计划还不明确", "当时你会先做什么来保护自己或身边的人？"),
    "Q19": ("面对死亡威胁时的主导感受还不明确", "那一刻最先出现的是害怕、不舍、空白，还是其他感受？"),
    "Q20": ("0 到 10 的影响分数还不明确", "如果只选一个 0 到 10 的数字，你会选几分？"),
}

_Q20_CHINESE_VALUES = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def q20_numeric_values(response: str) -> list[int]:
    """Extract explicit Q20 numbers without treating ordinary prose as scores."""

    text = str(response or "").strip()
    arabic = [int(value) for value in re.findall(r"(?<!\d)(10|[0-9])(?!\d)", text)]
    if arabic:
        return arabic
    chinese = re.findall(r"([零一二两三四五六七八九十])\s*分", text)
    if chinese:
        return [_Q20_CHINESE_VALUES[value] for value in chinese]
    if re.fullmatch(r"[零一二两三四五六七八九十]", text):
        return [_Q20_CHINESE_VALUES[text]]
    return []


def load_rubrics(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in sorted((root / "rubrics").glob("Q*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result[data["id"]] = data
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return result


def _score(question_id: str, response: str) -> int:
    text = response.strip()
    if question_id == "Q20":
        values = q20_numeric_values(text)
        if len(values) == 1:
            value = values[0]
            return 0 if value <= 5 else 1 if value <= 8 else 2
    if any(token in text for token in HIGH):
        return 2
    if any(token in text for token in MID):
        return 1
    if question_id in {"Q06", "Q07"} and not any(token in text for token in ("朋友", "家人", "伴侣", "倾诉", "求助", "说说")):
        return 1
    return 0


def evidence_gap(question_id: str, response: str, rubric: dict[str, Any] | None = None) -> tuple[str, str, str] | None:
    """Return an item-aware semantic gap without treating length as a label.

    Short responses can be sufficient for prompts such as Q07. The baseline
    only asks for clarification when the response is empty/non-semantic,
    explicitly ambiguous, invalid for the numeric item, or a single generic
    character outside the adjective-style item.
    """

    text = response.strip().strip("。！？!?，,；; ")
    target_gap, question = GAP_PROBES.get(
        question_id,
        ("回答的具体方向还不明确", "你能用一个具体感受、想法或做法补充说明吗？"),
    )
    if question_id == "Q20":
        matches = q20_numeric_values(text)
        if len(matches) != 1 or not 0 <= matches[0] <= 10:
            return "INVALID_NUMERIC_RESPONSE", target_gap, question
        return None
    if not text or not re.search(r"[\w\u4e00-\u9fff]", text):
        return "NO_SEMANTIC_CONTENT", target_gap, question
    if text in AMBIGUOUS:
        return "ABSTRACT_OR_DIRECTION_UNKNOWN", target_gap, question
    if len(text) == 1 and question_id != "Q07":
        return "MINIMAL_CONTEXT", target_gap, question
    return None


def score_response(question_id: str, response: str, rubrics: dict[str, dict[str, Any]]) -> ScoreResult:
    rubric = rubrics.get(question_id, {"version": "unknown"})
    score = _score(question_id, response)
    gap = evidence_gap(question_id, response, rubric)
    spans: list[Evidence] = []
    for token in HIGH + MID + AMBIGUOUS:
        start = response.find(token)
        if start >= 0:
            spans.append(Evidence(text=token, start=start, end=start + len(token), rule="词语线索需结合题目 rubric 解读"))
            if len(spans) >= 3:
                break
    sufficient = "INSUFFICIENT" if gap else "SUFFICIENT"
    confidence = 0.48 if gap else min(0.96, 0.62 + min(len(response), 40) / 100)
    rationale = f"依据 {question_id} 的 rubric 对回答进行可复核初评：倾向 {score} 分。"
    if gap:
        rationale += f" 当前证据不足，缺失信息：{gap[1]}。"
    elif spans:
        rationale += " 已标记原文线索，需由专家确认其与该题构念的对应关系。"
    else:
        rationale += " 未发现明确的风险方向词，仍应结合完整语境审阅。"
    return ScoreResult(
        question_id=question_id,
        response=response,
        preliminary_score=score,
        score_status="PROVISIONAL" if gap else "CONFIRMED",
        evidence_sufficiency=sufficient,
        rationale=rationale,
        evidence_spans=spans,
        confidence=round(confidence, 3),
        target_gap=gap[1] if gap else None,
        clarification_question=gap[2] if gap else None,
        rubric_version=str(rubric.get("version", "unknown")),
        decision_reasons=[gap[0]] if gap else [],
    )
