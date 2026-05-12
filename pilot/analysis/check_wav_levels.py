from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize WAV amplitude levels and flag near-silent captures.")
    parser.add_argument("input", type=Path, help="A .wav file or a directory containing .wav files.")
    parser.add_argument("--pattern", default="*.wav", help="Glob used when the input path is a directory.")
    parser.add_argument("--peak-threshold", type=int, default=256, help="Peak threshold below which a file is flagged low-level.")
    parser.add_argument("--rms-threshold", type=float, default=32.0, help="RMS threshold below which a file is flagged low-level.")
    return parser.parse_args()


def resolve_inputs(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob(pattern) if candidate.is_file())


def read_pcm16(path: Path) -> tuple[int, int, int, tuple[int, ...]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)

    if sample_width != 2:
        raise RuntimeError(f"Unsupported sample width {sample_width} for {path}")

    sample_count = len(frames) // sample_width
    samples = struct.unpack("<" + "h" * sample_count, frames)
    return channels, sample_rate, frame_count, samples


def summarize(path: Path, peak_threshold: int, rms_threshold: float) -> dict[str, object]:
    channels, sample_rate, frame_count, samples = read_pcm16(path)

    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    mean_abs = sum(abs(value) for value in samples) / len(samples)
    zero_ratio = sum(1 for value in samples if value == 0) / len(samples)
    peak_dbfs = -float("inf") if peak == 0 else 20.0 * math.log10(peak / 32767.0)
    likely_silent = peak < peak_threshold or rms < rms_threshold

    return {
        "file": str(path),
        "channels": channels,
        "sample_rate_hz": sample_rate,
        "duration_seconds": frame_count / sample_rate,
        "peak": peak,
        "peak_dbfs": round(peak_dbfs, 2) if math.isfinite(peak_dbfs) else "-inf",
        "rms": round(rms, 2),
        "mean_abs": round(mean_abs, 2),
        "zero_ratio": round(zero_ratio, 4),
        "likely_silent": likely_silent,
    }


def main() -> int:
    args = parse_args()
    inputs = resolve_inputs(args.input, args.pattern)
    if not inputs:
        raise SystemExit(f"No wav files found under {args.input}")

    summaries = [summarize(path, args.peak_threshold, args.rms_threshold) for path in inputs]
    print(json.dumps(summaries, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())