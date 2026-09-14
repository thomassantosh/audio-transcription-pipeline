import importlib
import os
import unittest
from unittest.mock import patch

TEST_ENV = {
    "SPEECH_KEY": "test-key",
    "SPEECH_REGION": "eastus",
    "AI_FOUNDRY_ENDPOINT": "https://example.services.ai.azure.com",
    "STORAGE_CONNECTION_STRING": (
        "DefaultEndpointsProtocol=https;AccountName=test;"
        "AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
    ),
}


def load_function_app():
    with patch.dict(os.environ, TEST_ENV):
        module = importlib.import_module("function_app.function_app")
        return importlib.reload(module)


class TimestampFormattingTests(unittest.TestCase):
    def test_format_timestamp_pads_hours_minutes_seconds(self):
        module = load_function_app()
        self.assertEqual(module.format_timestamp(0), "00:00:00")
        self.assertEqual(module.format_timestamp(65.9), "00:01:05")
        self.assertEqual(module.format_timestamp(3661), "01:01:01")


class BuildTimestampedTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.module = load_function_app()

    def test_includes_offsets_and_speakers_when_diarized(self):
        result = {
            "recognizedPhrases": [
                {
                    "recognitionStatus": "Success",
                    "speaker": 1,
                    "offsetInTicks": 16_000_000,  # 1.6s
                    "nBest": [{"display": "Hello there."}],
                },
                {
                    "recognitionStatus": "Success",
                    "speaker": 2,
                    "offsetInTicks": 650_000_000,  # 65s
                    "nBest": [{"display": "General Kenobi."}],
                },
            ]
        }
        self.assertEqual(
            self.module.build_timestamped_transcript(result),
            "[00:00:01] Speaker 1: Hello there.\n"
            "[00:01:05] Speaker 2: General Kenobi.",
        )

    def test_omits_speaker_label_when_not_present(self):
        result = {
            "recognizedPhrases": [
                {
                    "offsetInTicks": 0,
                    "nBest": [{"display": "Single speaker line."}],
                }
            ]
        }
        self.assertEqual(
            self.module.build_timestamped_transcript(result),
            "[00:00:00] Single speaker line.",
        )

    def test_skips_failed_and_empty_phrases(self):
        result = {
            "recognizedPhrases": [
                {"recognitionStatus": "Failure", "nBest": [{"display": "nope"}]},
                {"recognitionStatus": "Success", "nBest": [{"display": "   "}]},
                {"recognitionStatus": "Success", "nBest": []},
                {
                    "recognitionStatus": "Success",
                    "offsetInTicks": 30_000_000,
                    "nBest": [{"display": "Kept."}],
                },
            ]
        }
        self.assertEqual(
            self.module.build_timestamped_transcript(result),
            "[00:00:03] Kept.",
        )

    def test_returns_empty_string_without_phrases(self):
        self.assertEqual(self.module.build_timestamped_transcript({}), "")


if __name__ == "__main__":
    unittest.main()
