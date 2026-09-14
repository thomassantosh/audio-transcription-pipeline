#!/usr/bin/env python3
"""Build a timestamped transcript from an Azure Speech batch transcription JSON.

Reads the transcription result (from a file path argument or stdin) and writes a
plain-text transcript where each phrase is prefixed with its start time, and a
speaker label when diarization is enabled:

    [HH:MM:SS] Speaker 1: <phrase text>
    [HH:MM:SS] <phrase text>   # when no speaker information is present

The input is decoded as UTF-8 with BOM tolerance, since the Speech Service
sometimes serves the transcription JSON with a leading byte-order mark.
"""

import argparse
import json
import sys


def format_timestamp(seconds: float) -> str:
    """Format a number of seconds as an HH:MM:SS timestamp."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_timestamped_transcript(transcription_result: dict) -> str:
    """Build a timestamped transcript from a Speech batch transcription result."""
    lines = []
    for phrase in transcription_result.get("recognizedPhrases", []):
        if phrase.get("recognitionStatus", "Success") != "Success":
            continue

        n_best = phrase.get("nBest") or []
        display = n_best[0].get("display", "").strip() if n_best else ""
        if not display:
            continue

        offset_ticks = phrase.get("offsetInTicks")
        # Ticks are 100-nanosecond units; 10,000,000 ticks == 1 second.
        offset_seconds = offset_ticks / 10_000_000 if offset_ticks is not None else 0
        timestamp = format_timestamp(offset_seconds)

        speaker = phrase.get("speaker")
        if speaker is not None:
            lines.append(f"[{timestamp}] Speaker {speaker}: {display}")
        else:
            lines.append(f"[{timestamp}] {display}")

    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to the transcription JSON file, or '-' to read from stdin.",
    )
    args = parser.parse_args(argv)

    if args.input == "-":
        raw = sys.stdin.buffer.read()
    else:
        with open(args.input, "rb") as handle:
            raw = handle.read()

    if not raw.strip():
        print("Error: transcription JSON was empty.", file=sys.stderr)
        return 1

    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except json.JSONDecodeError as error:
        print(f"Error: could not parse transcription JSON: {error}", file=sys.stderr)
        return 1

    transcript = build_timestamped_transcript(data)
    if not transcript:
        print("Error: no recognized phrases found in transcription JSON.", file=sys.stderr)
        return 1

    print(transcript)
    return 0


if __name__ == "__main__":
    sys.exit(main())
