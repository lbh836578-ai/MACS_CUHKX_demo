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
except ImportError:
    sf = None

try:
    from nexcsi import decoder as nex_decoder
except ImportError:
    nex_decoder = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate audio/CSI clap offset from exported traces or raw files.")
    parser.add_argument("--audio", required=True, type=Path, help="Audio .wav or exported .npz trace.")
    parser.add_argument("--csi", required=True, type=Path, help="CSI .pcap or exported .npz trace.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pilot/data/processed/preview/sync_alignment.json"),
        help="JSON file used for the alignment summary.",
    )
    parser.add_argument(
        "--plot-path",
        type=Path,
        default=Path("pilot/data/processed/preview/sync_alignment.png"),
        help="Path for the alignment preview plot.",
    )
    parser.add_argument(
        "--csi-rate",
        type=float,
        default=None,
        help="Packet rate in Hz. Required when the CSI trace file does not contain sample_rate_hz.",
    )
    parser.add_argument(
        "--decoder",
        default="raspberrypi",
        help="nexcsi decoder name used when --csi points to a raw pcap file.",
    )
    return parser.parse_args()


def smooth_trace(trace: np.ndarray, window: int) -> np.ndarray:
    window = max(1, window)
    if window == 1:
      return trace
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(trace, kernel, mode="same")


def normalize_trace(trace: np.ndarray) -> np.ndarray:
    trace = np.asarray(trace, dtype=np.float32)
    if trace.size == 0:
        raise ValueError("Received an empty trace")
    centered = trace - trace.mean()
    scale = centered.std()
    if scale == 0:
        return centered
    return centered / scale


def load_audio_trace(path: Path) -> tuple[np.ndarray, float]:
    if path.suffix == ".npz":
        payload = np.load(path)
        if "mono" not in payload or "sample_rate_hz" not in payload:
            raise ValueError(f"Audio trace file {path} does not contain mono/sample_rate_hz")
        return payload["mono"], float(payload["sample_rate_hz"])

    if path.suffix != ".wav":
        raise ValueError(f"Unsupported audio input: {path}")
    if sf is None:
        raise SystemExit("Missing dependency: soundfile. Install with `pip install soundfile numpy matplotlib`.")

    samples, sample_rate = sf.read(str(path), always_2d=True)
    return samples.mean(axis=1), float(sample_rate)


def load_csi_trace(path: Path, decoder_name: str, sample_rate_override: float | None) -> tuple[np.ndarray, float]:
    if path.suffix == ".npz":
        payload = np.load(path)
        if "trace" not in payload:
            raise ValueError(f"CSI trace file {path} does not contain trace")
        sample_rate_hz = float(payload.get("sample_rate_hz", np.nan))
        if np.isnan(sample_rate_hz):
            if sample_rate_override is None:
                raise ValueError("CSI sample rate is missing. Use --csi-rate to provide packet rate.")
            sample_rate_hz = sample_rate_override
        return payload["trace"], sample_rate_hz

    if path.suffix != ".pcap":
        raise ValueError(f"Unsupported CSI input: {path}")
    if nex_decoder is None:
        raise SystemExit("Missing dependency: nexcsi. Install with `pip install nexcsi numpy matplotlib`.")
    if sample_rate_override is None:
        raise ValueError("Raw pcap alignment requires --csi-rate because packet timestamps are not inferred here.")

    decoder_instance = nex_decoder(decoder_name)
    samples = decoder_instance.read_pcap(str(path))
    csi = decoder_instance.unpack(samples["csi"], zero_nulls=True, zero_pilots=True)
    magnitude = np.abs(np.asarray(csi))
    if magnitude.ndim == 1:
        trace = magnitude
    else:
        trace = magnitude.mean(axis=tuple(range(1, magnitude.ndim)))
    return trace, float(sample_rate_override)


def detect_audio_event(trace: np.ndarray) -> int:
    envelope = smooth_trace(np.abs(trace), window=256)
    return int(np.argmax(envelope))


def detect_csi_event(trace: np.ndarray) -> int:
    normalized = normalize_trace(trace)
    gradient = np.abs(np.diff(smooth_trace(normalized, window=5), prepend=normalized[0]))
    return int(np.argmax(gradient))


def export_plot(
    audio_trace: np.ndarray,
    audio_rate: float,
    csi_trace: np.ndarray,
    csi_rate: float,
    audio_event_idx: int,
    csi_event_idx: int,
    plot_path: Path,
) -> None:
    plot_path.parent.mkdir(parents=True, exist_ok=True)

    audio_time = np.arange(audio_trace.size) / audio_rate
    csi_time = np.arange(csi_trace.size) / csi_rate
    csi_offset = (audio_event_idx / audio_rate) - (csi_event_idx / csi_rate)
    csi_time_aligned = csi_time + csi_offset

    figure = plt.figure(figsize=(12, 5))
    axis = figure.add_subplot(111)
    axis.plot(audio_time, normalize_trace(audio_trace), label="audio", linewidth=1.0)
    axis.plot(csi_time_aligned, normalize_trace(csi_trace), label="csi-aligned", linewidth=1.0)
    axis.axvline(audio_event_idx / audio_rate, color="black", linestyle="--", linewidth=1.0)
    axis.set_xlabel("time (s)")
    axis.set_ylabel("normalized amplitude")
    axis.set_title("Audio/CSI clap alignment preview")
    axis.legend()
    figure.tight_layout()
    figure.savefig(plot_path, dpi=200)
    plt.close(figure)


def main() -> int:
    args = parse_args()

    try:
        audio_trace, audio_rate = load_audio_trace(args.audio)
        csi_trace, csi_rate = load_csi_trace(args.csi, args.decoder, args.csi_rate)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    audio_event_idx = detect_audio_event(audio_trace)
    csi_event_idx = detect_csi_event(csi_trace)

    audio_event_time = audio_event_idx / audio_rate
    csi_event_time = csi_event_idx / csi_rate
    offset_seconds = audio_event_time - csi_event_time

    args.output.parent.mkdir(parents=True, exist_ok=True)
    export_plot(
        audio_trace,
        audio_rate,
        csi_trace,
        csi_rate,
        audio_event_idx,
        csi_event_idx,
        args.plot_path,
    )

    result = {
        "audio_input": str(args.audio),
        "csi_input": str(args.csi),
        "audio_sample_rate_hz": audio_rate,
        "csi_sample_rate_hz": csi_rate,
        "audio_event_index": audio_event_idx,
        "csi_event_index": csi_event_idx,
        "audio_event_time_seconds": audio_event_time,
        "csi_event_time_seconds": csi_event_time,
        "offset_seconds": offset_seconds,
        "interpretation": "audio_time = csi_time + offset_seconds",
        "plot_path": str(args.plot_path),
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())