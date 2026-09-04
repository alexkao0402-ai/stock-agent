import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.ai_analysis import (
    AIConfigurationError,
    compact_ai_provider,
    generate_compact_summary,
    has_compact_ai_key,
)


class CompactSummaryProviderTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            [{"date": "2026-08-28", "close": 100.0, "volume": 1_000}]
        )

    @patch("src.ai_analysis.get_secret")
    def test_gemini_is_preferred_when_both_keys_exist(self, secret):
        secret.side_effect = lambda name: {
            "GEMINI_API_KEY": "gemini-test",
            "ANTHROPIC_API_KEY": "anthropic-test",
        }.get(name)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "- 摘要"}]}}]
        }
        with patch("src.ai_analysis.requests.post", return_value=response) as post:
            result = generate_compact_summary("TEST", self.frame)

        self.assertEqual(result, "- 摘要")
        self.assertEqual(compact_ai_provider(), "Gemini Flash-Lite")
        post.assert_called_once()

    @patch("src.ai_analysis.get_secret", return_value=None)
    def test_no_provider_is_reported_cleanly(self, _secret):
        self.assertFalse(has_compact_ai_key())
        self.assertIsNone(compact_ai_provider())
        with self.assertRaises(AIConfigurationError):
            generate_compact_summary("TEST", self.frame)

    @patch("src.ai_analysis.get_secret", return_value="gemini-test")
    def test_empty_gemini_response_fails_cleanly(self, _secret):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"candidates": []}
        with patch("src.ai_analysis.requests.post", return_value=response):
            with self.assertRaises(AIConfigurationError):
                generate_compact_summary("TEST", self.frame)


if __name__ == "__main__":
    unittest.main()
