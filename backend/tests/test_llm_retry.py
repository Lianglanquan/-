import json
import unittest
from http.client import RemoteDisconnected
from unittest.mock import patch

from backend.app.scoring.llm import OpenAICompatibleScorer


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class LLMRetryTest(unittest.TestCase):
    def test_provider_marks_direction_gap_as_disambiguation_probe(self) -> None:
        scorer = OpenAICompatibleScorer(
            {"Q16": {"version": "1.0.0", "question": "牵挂", "criteria": []}},
            api_key="test",
            base_url="https://kittyapi.xyz/v1",
            model="gpt-5.6-terra",
            timeout=1,
            max_retries=0,
            retry_backoff=0,
        )
        payload = {
            "choices": [{"message": {"content": json.dumps({
                "preliminary_score": 0,
                "rationale": "方向未明",
                "evidence_spans": [],
                "confidence": 0.4,
                "evidence_sufficiency": "INSUFFICIENT",
                "target_gap": "牵挂的正负方向还不明确",
                "clarification_question": "它更像支持、负担，还是两者都有？",
            }, ensure_ascii=False)}}]
        }
        with patch("backend.app.scoring.llm.urllib.request.urlopen", return_value=_Response(payload)):
            result = scorer.score("Q16", "责任")

        self.assertEqual(result.probe_type, "DISAMBIGUATION")

    def test_provider_retries_a_transient_failure_before_returning_score(self) -> None:
        scorer = OpenAICompatibleScorer(
            {"Q01": {"version": "1.0.0", "question": "情绪", "criteria": []}},
            api_key="test",
            base_url="https://kittyapi.xyz/v1",
            model="gpt-5.6-terra",
            timeout=1,
            max_retries=1,
            retry_backoff=0,
        )
        payload = {
            "choices": [{"message": {"content": '{"preliminary_score":0,"rationale":"清楚","evidence_spans":[],"confidence":0.8,"evidence_sufficiency":"SUFFICIENT"}'}}]
        }
        calls = {"count": 0}

        def request(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("temporary")
            return _Response(payload)

        with patch("backend.app.scoring.llm.urllib.request.urlopen", side_effect=request):
            result = scorer.score("Q01", "平静")

        self.assertEqual(calls["count"], 2)
        self.assertEqual(result.preliminary_score, 0)

    def test_provider_retries_when_gateway_closes_connection(self) -> None:
        scorer = OpenAICompatibleScorer(
            {"Q01": {"version": "1.0.0", "question": "情绪", "criteria": []}},
            api_key="test",
            base_url="https://kittyapi.xyz/v1",
            model="gpt-5.6-terra",
            timeout=1,
            max_retries=1,
            retry_backoff=0,
        )
        payload = {
            "choices": [{"message": {"content": '{"preliminary_score":0,"rationale":"清楚","evidence_spans":[],"confidence":0.8,"evidence_sufficiency":"SUFFICIENT"}'}}]
        }
        calls = {"count": 0}

        def request(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RemoteDisconnected("gateway closed connection")
            return _Response(payload)

        with patch("backend.app.scoring.llm.urllib.request.urlopen", side_effect=request):
            result = scorer.score("Q01", "平静")

        self.assertEqual(calls["count"], 2)
        self.assertEqual(result.preliminary_score, 0)


if __name__ == "__main__":
    unittest.main()
