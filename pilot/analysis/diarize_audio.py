from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

try:
    import soundfile as sf
except ImportError as exc:  # pragma: no cover - dependency check
    raise SystemExit(
        "Missing dependency: soundfile. Install with `pip install soundfile pyannote.audio`."
    ) from exc

try:
    import torch
    from pyannote.audio import Pipeline
except ImportError as exc:  # pragma: no cover - dependency check
    raise SystemExit(
        "Missing dependency: pyannote.audio. Install with `pip install pyannote.audio soundfile`."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run speaker diarization on wav files.")
    parser.add_argument("input", type=Path, help="A .wav file or a directory containing .wav files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("pilot/data/processed/preview"),
        help="Directory for diarization JSON output.",
    )
    parser.add_argument("--pattern", default="*.wav", help="Glob used when the input path is a directory.")
    parser.add_argument(
        "--model",
        default="pyannote/speaker-diarization-3.1",
        help="Hugging Face model name passed to Pipeline.from_pretrained.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN"),
        help="Hugging Face access token. Defaults to HUGGINGFACE_TOKEN or HF_TOKEN.",
    )
    parser.add_argument(
        "--force-cpu",
        action="store_true",
        help="Do not move the pipeline to CUDA even when a GPU is available.",
    )
    return parser.parse_args()


def resolve_inputs(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob(pattern) if candidate.is_file())


def prepare_audio(path: Path, output_dir: Path) -> tuple[Path, Path | None]:
    samples, sample_rate = sf.read(str(path), always_2d=True)
    if samples.shape[1] == 1:
        return path, None

    output_dir.mkdir(parents=True, exist_ok=True)
    mono = samples.mean(axis=1).astype(np.float32)
    with tempfile.NamedTemporaryFile(
        prefix=f"{path.stem}_mono_",
        suffix=".wav",
        dir=output_dir,
        delete=False,
    ) as temporary_file:
        mono_path = Path(temporary_file.name)

    sf.write(str(mono_path), mono, sample_rate)
    return mono_path, mono_path


def main() -> int:
    args = parse_args()
    if not args.token:
        print("[ERROR] Missing Hugging Face token. Set --token or HUGGINGFACE_TOKEN.", file=sys.stderr)
        return 1

    inputs = resolve_inputs(args.input, args.pattern)
    if not inputs:
        print(f"No wav files found under {args.input}", file=sys.stderr)
        return 1

    pipeline = Pipeline.from_pretrained(args.model, use_auth_token=args.token)
    if not args.force_cpu and torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for wav_path in inputs:
        temp_path: Path | None = None
        try:
            prepared_path, temp_path = prepare_audio(wav_path, args.output_dir)
            diarization = pipeline(str(prepared_path))
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    {
                        "speaker": speaker,
                        "start_seconds": float(turn.start),
                        "end_seconds": float(turn.end),
                        "duration_seconds": float(turn.end - turn.start),
                    }
                )

            output_payload = {
                "input": str(wav_path),
                "model": args.model,
                "speaker_count": len(sorted({segment["speaker"] for segment in segments})),
                "segments": segments,
            }
            output_path = args.output_dir / f"{wav_path.stem}_diarization.json"
            output_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
            print(json.dumps({"input": str(wav_path), "output": str(output_path)}, ensure_ascii=True))
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())