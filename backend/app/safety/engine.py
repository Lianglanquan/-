"""Independent, conservative safety gate.

The gate only detects phrases requiring the pre-defined professional workflow;
it does not infer safety from a 0/1/2 score.
"""

from __future__ import annotations

from pydantic import BaseModel


class SafetyResult(BaseModel):
    state: str
    matched_terms: list[str]
    action: str


SAFETY_TERMS = ("自杀", "不想活", "结束生命", "伤害自己", "去死", "活不下去")


def screen(text: str) -> SafetyResult:
    matched = [term for term in SAFETY_TERMS if term in text]
    if matched:
        return SafetyResult(state="SAFETY_REVIEW", matched_terms=matched, action="停止自动澄清，转入专业人员预定义评估流程。")
    return SafetyResult(state="CLEAR", matched_terms=[], action="继续普通评分流程。")
