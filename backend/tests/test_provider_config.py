import os
import unittest
from pathlib import Path

from backend.app.scoring.engine import load_rubrics
from backend.app.scoring.llm import OpenAICompatibleScorer, configured_scorer


class ProviderConfigTest(unittest.TestCase):
    def test_external_permission_selects_configured_llm(self) -> None:
        keys = {
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
            "SCORING_PROVIDER": os.environ.get("SCORING_PROVIDER"),
            "ALLOW_EXTERNAL_SCORING": os.environ.get("ALLOW_EXTERNAL_SCORING"),
            "OPENAI_TIMEOUT": os.environ.get("OPENAI_TIMEOUT"),
            "OPENAI_MAX_RETRIES": os.environ.get("OPENAI_MAX_RETRIES"),
            "OPENAI_RETRY_BACKOFF": os.environ.get("OPENAI_RETRY_BACKOFF"),
        }
        try:
            os.environ.update({
                "OPENAI_API_KEY": "unit-test-key",
                "OPENAI_BASE_URL": "https://kittyapi.xyz/v1",
                "OPENAI_MODEL": "gpt-5.6-terra",
                "SCORING_PROVIDER": "llm",
                "ALLOW_EXTERNAL_SCORING": "true",
                "OPENAI_TIMEOUT": "9",
                "OPENAI_MAX_RETRIES": "1",
                "OPENAI_RETRY_BACKOFF": "0.2",
            })
            scorer, mode = configured_scorer(load_rubrics(Path(__file__).resolve().parents[2]))
            self.assertEqual(mode, "llm")
            self.assertIsInstance(scorer, OpenAICompatibleScorer)
            self.assertEqual(scorer.model, "gpt-5.6-terra")
            self.assertEqual(scorer.timeout, 9)
            self.assertEqual(scorer.max_retries, 1)
            self.assertEqual(scorer.retry_backoff, 0.2)
        finally:
            for key, value in keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
