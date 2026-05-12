from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

try:
    import soundfile as sf
except ImportError as exc:  # pragma: no cover - dependency check
    raise SystemExit(
        "Missing dependency: soundfile. Install with `pip install soundfile numpy matplotlib`."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate waveform, RMS, and spectrum previews for wav files.")
    parser.add_argument("input", type=Path, help="A .wav file or directory containing .wav files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("pilot/data/processed/preview"),
        help="Directory used for figures, summaries, and trace exports.",
    )
    parser.add_argument("--pattern", default="*.wav", help="Glob used when the input path is a directory.")
    parser.add_argument("--channel", type=int, default=0, help="Preferred channel index for plotting.")
    parser.add_argument("--frame-ms", type=float, default=25.0, help="RMS frame length in milliseconds.")
    parser.add_argument("--hop-ms", type=float, default=10.0, help="RMS hop size in milliseconds.")
    parser.add_argument(
        "--max-points",
        type=int,
        default=12000,
        help="Maximum number of samples drawn in the waveform plot.",
    )
    return parser.parse_args()


def resolve_inputs(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob(pattern) if candidate.is_file())


def downsample_trace(trace: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if trace.size <= max_points:
        indices = np.arange(trace.size)
        return indices, trace

    step = max(1, int(np.ceil(trace.size / max_points)))
    indices = np.arange(0, trace.size, step)
    return indices, trace[indices]


def compute_rms(trace: np.ndarray, sample_rate: int, frame_ms: float, hop_ms: float) -> tuple[np.ndarray, np.ndarray]:
    frame_length = max(1, int(sample_rate * frame_ms / 1000.0))
    hop_length = max(1, int(sample_rate * hop_ms / 1000.0))

    if trace.size < frame_length:
        rms = np.array([np.sqrt(np.mean(np.square(trace)))])
        times = np.array([0.0])
        return times, rms

    frame_starts = np.arange(0, trace.size - frame_length + 1, hop_length)
    rms = np.array([
        np.sqrt(np.mean(np.square(trace[start : start + frame_length]))) for start in frame_starts
    ])
    times = frame_starts / float(sample_rate)
    return times, rms


def summarize_audio(
    wav_path: Path,
    output_dir: Path,
    channel: int,
    frame_ms: float,
    hop_ms: float,
    max_points: int,
) -> dict[str, object]:
    samples, sample_rate = sf.read(str(wav_path), always_2d=True)
    mono = samples.mean(axis=1)
    channel_index = min(max(channel, 0), samples.shape[1] - 1)
    selected = samples[:, channel_index]

    waveform_indices, waveform = downsample_trace(selected, max_points)
    waveform_times = waveform_indices / float(sample_rate)
    rms_times, rms = compute_rms(mono, sample_rate, frame_ms, hop_ms)

    spectrum = np.fft.rfft(mono)
    frequencies = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-9))

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = wav_path.stem
    png_path = output_dir / f"{stem}_audio_preview.png"
    json_path = output_dir / f"{stem}_audio_summary.json"
    npz_path = output_dir / f"{stem}_audio_trace.npz"

    figure = plt.figure(figsize=(12, 8))
    axis_wave = figure.add_subplot(311)
    axis_rms = figure.add_subplot(312)
    axis_spec = figure.add_subplot(313)

    axis_wave.plot(waveform_times, waveform, linewidth=0.8)
    axis_wave.set_title(stem)
    axis_wave.set_xlabel("time (s)")
    axis_wave.set_ylabel("amplitude")

    axis_rms.plot(rms_times, rms, linewidth=1.0)
    axis_rms.set_xlabel("time (s)")
    axis_rms.set_ylabel("RMS")

    axis_spec.plot(frequencies, magnitude_db, linewidth=0.8)
    axis_spec.set_xlabel("frequency (Hz)")
    axis_spec.set_ylabel("magnitude (dB)")
    axis_spec.set_xlim(0, sample_rate / 2.0)

    figure.tight_layout()
    figure.savefig(png_path, dpi=200)
    plt.close(figure)

    np.savez(
        npz_path,
        mono=mono.astype(np.float32),
        sample_rate_hz=float(sample_rate),
        rms=rms.astype(np.float32),
        rms_times=rms_times.astype(np.float32),
    )

    summary = {
        "wav": str(wav_path),
        "channels": int(samples.shape[1]),
        "sample_rate_hz": int(sample_rate),
        "duration_seconds": float(samples.shape[0] / float(sample_rate)),
        "selected_channel": int(channel_index),
        "rms_mean": float(rms.mean()),
        "rms_peak": float(rms.max()),
        "preview_png": str(png_path),
        "trace_npz": str(npz_path),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    inputs = resolve_inputs(args.input, args.pattern)
    if not inputs:
        print(f"No wav files found under {args.input}", file=sys.stderr)
        return 1

    summaries = []
    for wav_path in inputs:
        try:
            summary = summarize_audio(
                wav_path,
                args.output_dir,
                args.channel,
                args.frame_ms,
                args.hop_ms,
                args.max_points,
            )
        except Exception as exc:  # pragma: no cover - defensive CLI behavior
            print(f"[ERROR] {wav_path}: {exc}", file=sys.stderr)
            continue
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=True))

    if not summaries:
        return 1

    manifest_path = args.output_dir / "audio_preview_manifest.json"
    manifest_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())