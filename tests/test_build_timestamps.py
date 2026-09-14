import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_timestamps

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_timestamps.py"


class BuildTimestampsScriptTests(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(build_timestamps.format_timestamp(0), "00:00:00")
        self.assertEqual(build_timestamps.format_timestamp(65.9), "00:01:05")
        self.assertEqual(build_timestamps.format_timestamp(3661), "01:01:01")

    def test_build_with_speakers(self):
        result = {
            "recognizedPhrases": [
                {
                    "recognitionStatus": "Success",
                    "speaker": 1,
                    "offsetInTicks": 16_000_000,
                    "nBest": [{"display": "Hello there."}],
                },
                {
                    "recognitionStatus": "Success",
                    "speaker": 2,
                    "offsetInTicks": 650_000_000,
                    "nBest": [{"display": "General Kenobi."}],
                },
            ]
        }
        self.assertEqual(
            build_timestamps.build_timestamped_transcript(result),
            "[00:00:01] Speaker 1: Hello there.\n"
            "[00:01:05] Speaker 2: General Kenobi.",
        )

    def test_build_without_speaker(self):
        result = {
            "recognizedPhrases": [
                {"offsetInTicks": 0, "nBest": [{"display": "Single line."}]}
            ]
        }
        self.assertEqual(
            build_timestamps.build_timestamped_transcript(result),
            "[00:00:00] Single line.",
        )

    def test_cli_parses_bom_encoded_file(self):
        payload = json.dumps(
            {
                "recognizedPhrases": [
                    {
                        "recognitionStatus": "Success",
                        "offsetInTicks": 16_000_000,
                        "nBest": [{"display": "BOM works."}],
                    }
                ]
            }
        )
        # Prepend a UTF-8 BOM, as the Speech Service sometimes does.
        data = b"\xef\xbb\xbf" + payload.encode("utf-8")
        with patch("sys.stdin", io.TextIOWrapper(io.BytesIO(data))):
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = build_timestamps.main(["-"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "[00:00:01] BOM works.")

    def test_cli_reports_empty_input(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), "-"],
            input=b"",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"empty", result.stderr.lower())

    def test_cli_reports_no_phrases(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), "-"],
            input=b"{}",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"no recognized phrases", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
