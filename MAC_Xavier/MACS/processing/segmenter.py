"""
segmenter.py
------------
Parse a raw session directory and segment frame references by action
label, using ``timestamps.csv`` and ``session_meta.json``.

The segmenter does **not** move or copy any files — it only produces a
mapping that downstream stages (FrameExporter) consume.
"""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class FrameRef:
    """Reference to a single raw frame on disk."""
    seq: int
    modality: str
    timestamp_ns: int
    label: str
    path: Path            # absolute path to the raw file


@dataclass
class ActionSegment:
    """All frames belonging to one action label."""
    label: str
    start_timestamp_ns: int = 0
    end_timestamp_ns: int = 0
    frames: Dict[str, List[FrameRef]] = field(default_factory=dict)
    # frames: {"RGB": [FrameRef, ...], "Depth": [...], ...}


class Segmenter:
    """Read raw session metadata and group frames by action label."""

    ALL_MODALITIES = ("RGB", "Depth", "IR", "Thermal")

    def __init__(self, session_dir):
        """
        Parameters
        ----------
        session_dir : str or Path
            Path to a raw session directory, e.g.
            ``data/raw/session_20260330_143000/``.
        """
        self._session_dir = Path(session_dir)
        self._meta = {}
        self._segments = []

    @property
    def session_dir(self):
        return self._session_dir

    @property
    def meta(self):
        return self._meta

    @property
    def segments(self) -> List[ActionSegment]:
        return self._segments

    # ================================================================
    # Public API
    # ================================================================

    def run(self) -> List[ActionSegment]:
        """Parse the session and return ordered ActionSegments."""
        self._meta = self._load_meta()
        timestamps = self._load_timestamps()
        self._segments = self._group_by_label(timestamps)
        return self._segments

    # ================================================================
    # Internal helpers
    # ================================================================

    def _load_meta(self) -> dict:
        meta_path = self._session_dir / "session_meta.json"
        with open(meta_path, "r") as fh:
            return json.load(fh)

    def _load_timestamps(self) -> List[FrameRef]:
        """Read timestamps.csv and resolve each row to a FrameRef."""
        csv_path = self._session_dir / "timestamps.csv"
        refs = []
        save_formats = self._meta.get("save_formats", {})

        with open(csv_path, "r", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                seq = int(row["seq"])
                modality = row["modality"]
                timestamp_ns = int(row["timestamp_ns"])
                label = row["label"]

                # Resolve the file path on disk
                ext = self._ext_for_format(save_formats.get(modality, "npy"))
                filename = f"frame_{seq:06d}{ext}"
                path = self._session_dir / modality / filename

                refs.append(FrameRef(
                    seq=seq,
                    modality=modality,
                    timestamp_ns=timestamp_ns,
                    label=label,
                    path=path,
                ))
        return refs

    def _group_by_label(self, refs: List[FrameRef]) -> List[ActionSegment]:
        """Group FrameRefs by label, preserving the label order from meta."""
        labels = self._meta.get("labels", [])
        if not labels:
            # Fallback: derive order from first appearance in timestamps
            seen = []
            for r in refs:
                if r.label not in seen:
                    seen.append(r.label)
            labels = seen

        # Build per-label, per-modality lists
        seg_map = {}
        for label in labels:
            seg_map[label] = ActionSegment(label=label)
            for mod in self.ALL_MODALITIES:
                seg_map[label].frames[mod] = []

        for ref in refs:
            seg = seg_map.get(ref.label)
            if seg is None:
                continue
            seg.frames.setdefault(ref.modality, []).append(ref)

        # Compute start / end timestamps per segment
        for seg in seg_map.values():
            all_ts = []
            for frame_list in seg.frames.values():
                for fr in frame_list:
                    all_ts.append(fr.timestamp_ns)
            if all_ts:
                seg.start_timestamp_ns = min(all_ts)
                seg.end_timestamp_ns = max(all_ts)

        return [seg_map[l] for l in labels if l in seg_map]

    # ================================================================
    # Utilities
    # ================================================================

    @staticmethod
    def _ext_for_format(fmt):
        return {
            "npy":  ".npy",
            "jpg":  ".jpg",
            "jpeg": ".jpg",
            "png":  ".png",
        }.get(fmt, ".npy")
