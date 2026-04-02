"""
pipeline.py
-----------
Orchestrates the full post-processing pipeline:

1. **Segment** — parse raw session → ActionSegments
2. **Export**  — copy / convert frames + assemble videos
3. **Validate** — cross-check frame counts, write metadata.json
4. **Report** — generate ``session_report.json``

The pipeline runs in a background ``QThread`` so it never blocks the UI.
A ``progress`` signal reports percentage and status text continuously.
"""

import json
import time
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from .segmenter import Segmenter
from .frame_exporter import FrameExporter
from .validator import Validator


class PostProcessor(QThread):
    """Background thread that runs the full post-processing pipeline."""

    # (percent 0–100, status_text)
    progress = pyqtSignal(int, str)

    # Emitted once on success with the processed session dir path.
    finished_ok = pyqtSignal(str)

    # Emitted on failure with an error message.
    finished_error = pyqtSignal(str)

    def __init__(self, session_dir, config=None, parent=None):
        """
        Parameters
        ----------
        session_dir : str or Path
            Path to the raw session, e.g.
            ``data/raw/session_20260330_143000/``.
        config : dict, optional
            Full application config.
        """
        super().__init__(parent)
        self._session_dir = Path(session_dir)
        self._cfg = config or {}
        self._output_dir = None   # set during run()

    @property
    def output_dir(self):
        return self._output_dir

    # ================================================================
    # QThread entry point
    # ================================================================

    def run(self):
        try:
            self._run_pipeline()
        except Exception as exc:
            self.finished_error.emit(f"Post-processing failed: {exc}")

    # ================================================================
    # Pipeline stages
    # ================================================================

    def _run_pipeline(self):
        t0 = time.monotonic()

        # --- Resolve output dir -------------------------------------------
        rec_cfg = self._cfg.get("recording", {})
        base_dir = rec_cfg.get("output_dir", "data")
        proc_sub = rec_cfg.get("processed_subdir", "processed")
        session_name = self._session_dir.name       # session_YYYYMMDD_HHMMSS
        self._output_dir = Path(base_dir) / proc_sub / session_name
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Extract session_id from directory name
        session_id = session_name.replace("session_", "")

        # --- Step 1: Segment -----------------------------------------------
        self.progress.emit(5, "Parsing session metadata…")
        segmenter = Segmenter(self._session_dir)
        segments = segmenter.run()

        if not segments:
            self.finished_error.emit("No action segments found in session.")
            return

        n_actions = len(segments)
        self.progress.emit(10, f"Found {n_actions} action(s)")

        # --- Step 2 & 3: Export frames + videos ----------------------------
        exporter = FrameExporter(
            output_root=self._output_dir,
            config=self._cfg,
            progress_cb=self._export_progress_cb,
        )

        action_dirs = []
        for idx, seg in enumerate(segments):
            base_pct = 10 + int(70 * idx / n_actions)
            self.progress.emit(
                base_pct,
                f"Exporting [{idx + 1}/{n_actions}] {seg.label}…",
            )
            action_dir = exporter.export(seg)
            action_dirs.append(action_dir)

        self.progress.emit(80, "Exporting complete")

        # --- Step 4: Validate & write metadata per action ------------------
        validator = Validator(config=self._cfg)
        results = []
        for idx, (seg, adir) in enumerate(zip(segments, action_dirs)):
            self.progress.emit(
                80 + int(15 * idx / n_actions),
                f"Validating [{idx + 1}/{n_actions}] {seg.label}…",
            )
            result = validator.validate(adir, seg, session_id=session_id)
            results.append(result)

        # --- Step 5: Session report ----------------------------------------
        self.progress.emit(95, "Writing session report…")
        report = self._build_report(
            segmenter.meta, segments, results, time.monotonic() - t0,
        )
        report_path = self._output_dir / "session_report.json"
        with open(report_path, "w") as fh:
            json.dump(report, fh, indent=2)

        self.progress.emit(100, "Done")
        self.finished_ok.emit(str(self._output_dir))

    # ================================================================
    # Report generation
    # ================================================================

    @staticmethod
    def _build_report(meta, segments, results, elapsed_sec):
        actions = []
        all_ok = True
        for seg, res in zip(segments, results):
            entry = {
                "label": seg.label,
                "frame_counts": res.frame_counts,
                "duration_sec": round(
                    (seg.end_timestamp_ns - seg.start_timestamp_ns) / 1e9, 2
                ),
                "validation_ok": res.ok,
                "warnings": res.warnings,
            }
            actions.append(entry)
            if not res.ok:
                all_ok = False

        return {
            "session_id": meta.get("labels", []),
            "labels": meta.get("labels", []),
            "num_actions": len(segments),
            "recording_duration_sec": round(
                (meta.get("recording_stop_ns", 0)
                 - meta.get("recording_start_ns", 0)) / 1e9,
                2,
            ),
            "processing_duration_sec": round(elapsed_sec, 2),
            "all_valid": all_ok,
            "actions": actions,
        }

    # ================================================================
    # Progress helper
    # ================================================================

    def _export_progress_cb(self, message, current, total):
        """Relayed from FrameExporter — too frequent to emit every call."""
        # Emit at most every 20 frames to avoid flooding the signal queue
        if current % 20 == 0 or current == total - 1:
            self.progress.emit(-1, f"{message} ({current + 1}/{total})")
