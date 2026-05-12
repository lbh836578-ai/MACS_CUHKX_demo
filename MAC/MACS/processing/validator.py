"""
validator.py
------------
Validate a processed action directory:

* Check that all 4 modalities have frame output.
* Cross-check frame counts between modalities.
* Generate ``metadata.json`` with per-action statistics.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from .segmenter import ActionSegment


class ValidationResult:
    """Result of validating one action segment."""

    __slots__ = ("label", "frame_counts", "warnings", "ok")

    def __init__(self, label):
        self.label = label
        self.frame_counts: Dict[str, int] = {}
        self.warnings: List[str] = []
        self.ok = True

    def add_warning(self, msg):
        self.warnings.append(msg)
        self.ok = False


class Validator:
    """Validate processed output and generate metadata."""

    ALL_MODALITIES = ("RGB", "Depth", "IR", "Thermal")

    _FRAME_DIRS = {
        "RGB":     "RGB_frames",
        "Depth":   "Depth_frames",
        "IR":      "IR_frames",
        "Thermal": "Thermal_frames",
    }

    _VIDEO_FILES = {
        "RGB":     "RGB_video/rgb.avi",
        "Depth":   "Depth_video/depth_colorized.avi",
        "IR":      "IR_video/ir.avi",
        "Thermal": "Thermal_video/thermal.avi",
    }

    def __init__(self, config: Optional[dict] = None):
        self._cfg = config or {}
        cam_cfg = self._cfg.get("camera", {})
        nyx = cam_cfg.get("nyx650", {})
        tb = cam_cfg.get("tb4117", {})

        self._res = {
            "RGB":     [nyx.get("rgb",   {}).get("width", 1600),
                        nyx.get("rgb",   {}).get("height", 1200)],
            "Depth":   [nyx.get("depth", {}).get("width", 640),
                        nyx.get("depth", {}).get("height", 480)],
            "IR":      [nyx.get("ir",    {}).get("width", 640),
                        nyx.get("ir",    {}).get("height", 480)],
            "Thermal": [tb.get("thermal", {}).get("width", 256),
                        tb.get("thermal", {}).get("height", 192)],
        }
        self._fps = {
            "RGB":     nyx.get("rgb",     {}).get("fps", 15),
            "Depth":   nyx.get("depth",   {}).get("fps", 15),
            "IR":      nyx.get("ir",      {}).get("fps", 15),
            "Thermal": tb.get("thermal",  {}).get("fps", 30),
        }

    # ================================================================
    # Public API
    # ================================================================

    def validate(
        self,
        action_dir: Path,
        segment: ActionSegment,
        session_id: str = "",
    ) -> ValidationResult:
        """Validate an exported action dir and write ``metadata.json``.

        Returns a ValidationResult summarising the check.
        """
        result = ValidationResult(segment.label)

        # Count output frames per modality
        for mod in self.ALL_MODALITIES:
            subdir = action_dir / self._FRAME_DIRS[mod]
            if not subdir.exists():
                result.frame_counts[mod] = 0
                result.add_warning(f"{mod}: frame directory missing")
                continue

            # Count PNG files as frames (Depth/IR also have .npy)
            pngs = list(subdir.glob("*.png"))
            result.frame_counts[mod] = len(pngs)

        # Cross-check frame counts between NYX650 modalities
        nyx_counts = {
            m: result.frame_counts.get(m, 0)
            for m in ("RGB", "Depth", "IR")
            if result.frame_counts.get(m, 0) > 0
        }
        if len(set(nyx_counts.values())) > 1:
            result.add_warning(
                f"NYX650 frame count mismatch: {nyx_counts}"
            )

        # Check videos exist
        for mod in self.ALL_MODALITIES:
            vpath = action_dir / self._VIDEO_FILES[mod]
            if result.frame_counts.get(mod, 0) > 0 and not vpath.exists():
                result.add_warning(f"{mod}: video file missing")

        # Compute duration
        duration_ns = segment.end_timestamp_ns - segment.start_timestamp_ns
        duration_sec = duration_ns / 1e9 if duration_ns > 0 else 0.0

        # Compute max sync drift among frames within this segment
        drift_ms = self._compute_segment_drift(segment)

        # Write metadata.json
        metadata = {
            "action_label": segment.label,
            "session_id": session_id,
            "duration_sec": round(duration_sec, 2),
            "frame_count": result.frame_counts,
            "resolution": self._res,
            "fps": self._fps,
            "sync_max_drift_ms": round(drift_ms, 2) if drift_ms else None,
            "start_timestamp_ns": segment.start_timestamp_ns,
            "end_timestamp_ns": segment.end_timestamp_ns,
            "validation_warnings": result.warnings,
        }
        meta_path = action_dir / "metadata.json"
        with open(meta_path, "w") as fh:
            json.dump(metadata, fh, indent=2)

        return result

    # ================================================================
    # Helpers
    # ================================================================

    @staticmethod
    def _compute_segment_drift(segment: ActionSegment) -> float:
        """Estimate the maximum inter-camera timestamp drift within
        this segment (NYX650 vs TB4117), in milliseconds.

        Uses a simple approach: for each NYX650 frame, find the
        closest TB4117 frame and measure the gap.
        """
        thermal_ts = sorted(
            fr.timestamp_ns for fr in segment.frames.get("Thermal", [])
        )
        if not thermal_ts:
            return 0.0

        # Use RGB as the NYX650 reference
        rgb_ts = sorted(
            fr.timestamp_ns for fr in segment.frames.get("RGB", [])
        )
        if not rgb_ts:
            return 0.0

        max_drift = 0.0
        t_idx = 0
        for rts in rgb_ts:
            # Advance thermal index to closest
            while (t_idx < len(thermal_ts) - 1
                   and abs(thermal_ts[t_idx + 1] - rts)
                   < abs(thermal_ts[t_idx] - rts)):
                t_idx += 1
            drift = abs(thermal_ts[t_idx] - rts) / 1e6  # ns → ms
            if drift > max_drift:
                max_drift = drift

        return max_drift
