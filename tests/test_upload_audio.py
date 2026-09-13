import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from azure.storage.blob import BlobServiceClient

from scripts import upload_audio


ROOT = Path(__file__).resolve().parents[1]


class UploadAudioTests(unittest.TestCase):
    def test_upload_configuration_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.mp3"
            audio.write_bytes(b"audio")
            with (
                patch.dict(os.environ, {
                    "STORAGE_CONNECTION_STRING": (
                        "DefaultEndpointsProtocol=https;AccountName=test;"
                        "AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
                    ),
                    "AUDIO_CONTAINER": "audio",
                }),
                patch.object(
                    upload_audio.BlobServiceClient,
                    "from_connection_string",
                    wraps=BlobServiceClient.from_connection_string,
                ) as create_client,
                patch("azure.storage.blob.BlobClient.exists", return_value=False),
                patch("azure.storage.blob.BlobClient.upload_blob") as upload,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                upload_audio.upload_audio(str(audio), True, "meeting")

            client_options = create_client.call_args.kwargs
            self.assertEqual(client_options["max_single_put_size"], 4 * 1024 * 1024)
            self.assertEqual(client_options["max_block_size"], 4 * 1024 * 1024)
            self.assertEqual(client_options["connection_timeout"], 120)
            upload.assert_called_once()
            self.assertTrue(upload.call_args.kwargs["overwrite"])
            self.assertEqual(
                upload.call_args.kwargs["metadata"],
                {"diarization": "true", "topic": "meeting"},
            )
            self.assertTrue(callable(upload.call_args.kwargs["progress_hook"]))

    def test_cli_reports_upload_failure(self):
        output = io.StringIO()
        with (
            patch("sys.argv", ["upload_audio.py", "recording.mp3"]),
            patch.object(upload_audio.os.path, "exists", return_value=True),
            patch.object(
                upload_audio, "upload_audio",
                side_effect=TimeoutError("The write operation timed out"),
            ),
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as error,
        ):
            upload_audio.main()
        self.assertEqual(error.exception.code, 1)
        self.assertIn("Error: The write operation timed out", output.getvalue())

    def test_make_completion_depends_on_upload_success(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.mp3"
            audio.write_bytes(b"audio")
            recipe = subprocess.run(
                [
                    "make", "--no-print-directory", "-n", "-o", "uv-sync",
                    "process-audio", f"FILE={audio}", "TOPIC=meeting",
                ],
                cwd=ROOT, capture_output=True, text=True, check=True,
            ).stdout
            for upload_status in (0, 1):
                with self.subTest(upload_status=upload_status):
                    result = subprocess.run(
                        ["/bin/sh", "-c", f"uv() {{ return {upload_status}; }}\n{recipe}"],
                        cwd=ROOT, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, upload_status)
                    self.assertEqual(
                        "Processing complete" in result.stdout,
                        upload_status == 0,
                    )


if __name__ == "__main__":
    unittest.main()
