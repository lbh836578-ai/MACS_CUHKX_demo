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
    from nexcsi import decoder as nex_decoder
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: nexcsi. Install with `pip install nexcsi numpy matplotlib`."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quick preview figures for Nexmon CSI captures.")
    parser.add_argument("input", type=Path, help="A .pcap file or a directory containing .pcap files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("pilot_6pi_wifi/data/processed/preview"),
        help="Directory used for figures, summaries, and trace exports.",
    )
    parser.add_argument(
        "--decoder",
        default="raspberrypi",
        help="nexcsi decoder name. Default: raspberrypi",
    )
    parser.add_argument(
        "--pattern",
        default="*.pcap",
        help="Glob used when the input path is a directory.",
    )
    parser.add_argument(
        "--packet-rate",
        type=float,
        default=None,
        help="Optional packet rate in Hz. Stored in the exported .npz for later sync.",
    )
    return parser.parse_args()


def resolve_inputs(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob(pattern) if candidate.is_file())


def build_trace(csi: np.ndarray) -> np.ndarray:
    magnitude = np.abs(np.asarray(csi))
    if magnitude.ndim == 1:
        return magnitude
    axes = tuple(range(1, magnitude.ndim))
    return magnitude.mean(axis=axes)


def summarize_capture(capture_path: Path, output_dir: Path, decoder_name: str, packet_rate: float | None) -> dict[str, object]:
    decoder_instance = nex_decoder(decoder_name)
    samples = decoder_instance.read_pcap(str(capture_path))
    csi = decoder_instance.unpack(samples["csi"], zero_nulls=True, zero_pilots=True)
    trace = build_trace(csi)

    if trace.size == 0:
        raise ValueError(f"No CSI trace data found in {capture_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = capture_path.stem
    png_path = output_dir / f"{stem}_csi_preview.png"
    json_path = output_dir / f"{stem}_csi_summary.json"
    npz_path = output_dir / f"{stem}_csi_trace.npz"

    figure = plt.figure(figsize=(10, 3))
    axis = figure.add_subplot(111)
    axis.plot(trace, linewidth=1.0)
    axis.set_title(stem)
    axis.set_xlabel("packet index")
    axis.set_ylabel("mean amplitude")
    figure.tight_layout()
    figure.savefig(png_path, dpi=200)
    plt.close(figure)

    sample_rate_hz = float(packet_rate) if packet_rate is not None else np.nan
    np.savez(
        npz_path,
        trace=trace.astype(np.float32),
        sample_rate_hz=sample_rate_hz,
        packet_indices=np.arange(trace.size, dtype=np.int32),
    )

    summary = {
        "capture": str(capture_path),
        "decoder": decoder_name,
        "packet_count": int(len(samples)),
        "csi_shape": list(np.asarray(csi).shape),
        "subcarriers": int(np.asarray(csi).shape[-1]),
        "mean_amplitude": float(np.abs(csi).mean()),
        "std_amplitude": float(trace.std()),
        "trace_npz": str(npz_path),
        "preview_png": str(png_path),
        "sample_rate_hz": None if packet_rate is None else packet_rate,
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    inputs = resolve_inputs(args.input, args.pattern)
    if not inputs:
        print(f"No pcap files found under {args.input}", file=sys.stderr)
        return 1

    summaries = []
    for capture_path in inputs:
        try:
            summary = summarize_capture(capture_path, args.output_dir, args.decoder, args.packet_rate)
        except Exception as exc:  # pragma: no cover
            print(f"[ERROR] {capture_path}: {exc}", file=sys.stderr)
            continue
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=True))

    if not summaries:
        return 1

    manifest_path = args.output_dir / "csi_preview_manifest.json"
    manifest_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
