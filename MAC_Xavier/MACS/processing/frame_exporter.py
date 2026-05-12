"""
frame_exporter.py
-----------------
For each ActionSegment produced by the Segmenter:

* Copy / convert raw frames into the processed directory structure.
* Assemble per-modality video clips.
* Generate visualisation images (depth colorized, IR normalised).

Output hierarchy (per action)::

    <action_label>/
        RGB_video/rgb.avi
        RGB_frames/frame_000000.png  ...
        Depth_video/depth_colorized.avi
        Depth_frames/frame_000000.npy  frame_000000.png  ...
        IR_video/ir.avi
        IR_frames/frame_000000.npy  frame_000000.png  ...
        Thermal_video/thermal.avi
        Thermal_frames/frame_000000.png  ...
"""

import shutil
from pathlib import Path
from typing import Callable, List, Optional, Union

import cv2
import numpy as np

from .segmenter import ActionSegment, FrameRef


class FrameExporter:
    """Export one ActionSegment into the standardised processed layout."""

    # Video codec / container
    FOURCC = cv2.VideoWriter_fourcc(*"MJPG")

    def __init__(
        self,
        output_root: Union[str, Path],
        config: Optional[dict] = None,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ):
        """
        Parameters
        ----------
        output_root : Path
            Processed session directory, e.g.
            ``data/processed/session_20260330_143000/``.
        config : dict, optional
            Full application config (camera resolution/fps info).
        progress_cb : callable, optional
            ``(message, current, total)`` callback for progress reporting.
        """
        self._root = Path(output_root)
        self._cfg = config or {}
        self._progress_cb = progress_cb

        cam_cfg = self._cfg.get("camera", {})
        nyx = cam_cfg.get("nyx650", {})
        tb = cam_cfg.get("tb4117", {})

        self._res = {
            "RGB":     (nyx.get("rgb",   {}).get("width", 1600),
                        nyx.get("rgb",   {}).get("height", 1200)),
            "Depth":   (nyx.get("depth", {}).get("width", 640),
                        nyx.get("depth", {}).get("height", 480)),
            "IR":      (nyx.get("ir",    {}).get("width", 640),
                        nyx.get("ir",    {}).get("height", 480)),
            "Thermal": (tb.get("thermal", {}).get("width", 256),
                        tb.get("thermal", {}).get("height", 192)),
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

    def export(self, segment: ActionSegment) -> Path:
        """Export *segment* and return the action output directory."""
        action_dir = self._root / segment.label
        action_dir.mkdir(parents=True, exist_ok=True)

        self._export_rgb(segment, action_dir)
        self._export_depth(segment, action_dir)
        self._export_ir(segment, action_dir)
        self._export_thermal(segment, action_dir)

        return action_dir

    # ================================================================
    # Per-modality exporters
    # ================================================================

    def _export_rgb(self, segment: ActionSegment, action_dir: Path):
        frames_dir = action_dir / "RGB_frames"
        video_dir = action_dir / "RGB_video"
        frames_dir.mkdir(exist_ok=True)
        video_dir.mkdir(exist_ok=True)

        refs = segment.frames.get("RGB", [])
        if not refs:
            return

        w, h = self._res["RGB"]
        fps = self._fps["RGB"]
        video_path = video_dir / "rgb.avi"
        writer = cv2.VideoWriter(str(video_path), self.FOURCC, fps, (w, h))

        for i, ref in enumerate(refs):
            self._report("RGB", i, len(refs))
            img = self._load_image(ref)
            if img is None:
                continue

            # Save frame as PNG
            out_path = frames_dir / f"frame_{i:06d}.png"
            cv2.imwrite(str(out_path), img)

            # Append to video
            if img.shape[1] != w or img.shape[0] != h:
                img = cv2.resize(img, (w, h))
            writer.write(img)

        writer.release()

    def _export_depth(self, segment: ActionSegment, action_dir: Path):
        frames_dir = action_dir / "Depth_frames"
        video_dir = action_dir / "Depth_video"
        frames_dir.mkdir(exist_ok=True)
        video_dir.mkdir(exist_ok=True)

        refs = segment.frames.get("Depth", [])
        if not refs:
            return

        w, h = self._res["Depth"]
        fps = self._fps["Depth"]
        video_path = video_dir / "depth_colorized.avi"
        writer = cv2.VideoWriter(str(video_path), self.FOURCC, fps, (w, h))

        for i, ref in enumerate(refs):
            self._report("Depth", i, len(refs))
            raw = self._load_npy(ref)
            if raw is None:
                continue

            # Save raw 16-bit .npy
            npy_path = frames_dir / f"frame_{i:06d}.npy"
            np.save(str(npy_path), raw)

            # Colorized visualisation
            vis = self._colorize_depth(raw)
            png_path = frames_dir / f"frame_{i:06d}.png"
            cv2.imwrite(str(png_path), vis)

            # Append to video
            if vis.shape[1] != w or vis.shape[0] != h:
                vis = cv2.resize(vis, (w, h))
            writer.write(vis)

        writer.release()

    def _export_ir(self, segment: ActionSegment, action_dir: Path):
        frames_dir = action_dir / "IR_frames"
        video_dir = action_dir / "IR_video"
        frames_dir.mkdir(exist_ok=True)
        video_dir.mkdir(exist_ok=True)

        refs = segment.frames.get("IR", [])
        if not refs:
            return

        w, h = self._res["IR"]
        fps = self._fps["IR"]
        video_path = video_dir / "ir.avi"
        writer = cv2.VideoWriter(str(video_path), self.FOURCC, fps, (w, h))

        for i, ref in enumerate(refs):
            self._report("IR", i, len(refs))
            raw = self._load_npy_or_image(ref)
            if raw is None:
                continue

            # Save raw .npy (preserves original bit-depth)
            npy_path = frames_dir / f"frame_{i:06d}.npy"
            np.save(str(npy_path), raw)

            # Normalised visualisation
            vis = self._normalize_ir(raw)
            png_path = frames_dir / f"frame_{i:06d}.png"
            cv2.imwrite(str(png_path), vis)

            # Append to video (needs BGR)
            if len(vis.shape) == 2:
                vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
            if vis.shape[1] != w or vis.shape[0] != h:
                vis = cv2.resize(vis, (w, h))
            writer.write(vis)

        writer.release()

    def _export_thermal(self, segment: ActionSegment, action_dir: Path):
        frames_dir = action_dir / "Thermal_frames"
        video_dir = action_dir / "Thermal_video"
        frames_dir.mkdir(exist_ok=True)
        video_dir.mkdir(exist_ok=True)

        refs = segment.frames.get("Thermal", [])
        if not refs:
            return

        w, h = self._res["Thermal"]
        fps = self._fps["Thermal"]
        video_path = video_dir / "thermal.avi"
        writer = cv2.VideoWriter(str(video_path), self.FOURCC, fps, (w, h))

        for i, ref in enumerate(refs):
            self._report("Thermal", i, len(refs))
            img = self._load_image(ref)
            if img is None:
                continue

            out_path = frames_dir / f"frame_{i:06d}.png"
            cv2.imwrite(str(out_path), img)

            if img.shape[1] != w or img.shape[0] != h:
                img = cv2.resize(img, (w, h))
            writer.write(img)

        writer.release()

    # ================================================================
    # Loaders
    # ================================================================

    @staticmethod
    def _load_image(ref: FrameRef):
        """Load a .jpg / .png image from disk."""
        if not ref.path.exists():
            return None
        img = cv2.imread(str(ref.path), cv2.IMREAD_UNCHANGED)
        return img

    @staticmethod
    def _load_npy(ref: FrameRef):
        """Load a .npy array from disk."""
        if not ref.path.exists():
            return None
        return np.load(str(ref.path))

    @staticmethod
    def _load_npy_or_image(ref: FrameRef):
        """Load .npy if available, else try imread."""
        if not ref.path.exists():
            return None
        if ref.path.suffix == ".npy":
            return np.load(str(ref.path))
        return cv2.imread(str(ref.path), cv2.IMREAD_UNCHANGED)

    # ================================================================
    # Visualisation helpers
    # ================================================================

    @staticmethod
    def _colorize_depth(depth):
        """Convert 16-bit depth map to a JET colormap BGR image."""
        if depth is None:
            return None
        # Clip to reasonable range and normalise to 0–255
        max_val = np.max(depth) if np.max(depth) > 0 else 1
        norm = (depth.astype(np.float32) / max_val * 255).astype(np.uint8)
        return cv2.applyColorMap(norm, cv2.COLORMAP_JET)

    @staticmethod
    def _normalize_ir(ir):
        """Normalise IR to 8-bit grayscale for visualisation."""
        if ir is None:
            return None
        if ir.dtype == np.uint8:
            return ir
        # 16-bit or float → normalise
        max_val = np.max(ir) if np.max(ir) > 0 else 1
        return (ir.astype(np.float32) / max_val * 255).astype(np.uint8)

    # ================================================================
    # Progress
    # ================================================================

    def _report(self, modality, current, total):
        if self._progress_cb is not None:
            self._progress_cb(f"Exporting {modality}", current, total)
