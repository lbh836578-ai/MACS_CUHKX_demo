"""
recorder.py
-----------
Persists captured frames and session metadata to disk.

Design
~~~~~~
*   An **AsyncFrameWriter** (plain ``threading.Thread``) owns a bounded
    queue and writes frames in a background thread so that camera capture
    is never blocked by I/O.
*   **SessionRecorder** creates the session directory tree, feeds frames
    to the async writer, accumulates timestamps in memory, and writes
    ``timestamps.csv`` + ``session_meta.json`` on finalisation.

Directory layout
~~~~~~~~~~~~~~~~
::

    data/raw/session_20260330_143012/
        session_meta.json
        timestamps.csv
        RGB/
            frame_000000.jpg
            ...
        Depth/
            frame_000000.npy
            ...
        IR/
            frame_000000.npy
            ...
        Thermal/
            frame_000000.jpg
            ...
"""

import csv
import json
import os
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Async writer
# ---------------------------------------------------------------------------

class AsyncFrameWriter(threading.Thread):
    """Daemon thread that drains a frame queue and writes to disk."""

    def __init__(self, maxsize=600, jpg_quality=95):
        super().__init__(daemon=True)
        self._queue = queue.Queue(maxsize=maxsize)
        self._stop_event = threading.Event()
        self._jpg_quality = jpg_quality
        self.stats = {"written": 0, "dropped": 0, "errors": 0}

    # -- public interface ----------------------------------------------------

    def enqueue(self, filepath, data, fmt="npy"):
        """Push a write task.  Drops the frame if the queue is full."""
        try:
            self._queue.put_nowait((str(filepath), data, fmt))
        except queue.Full:
            self.stats["dropped"] += 1

    def request_stop(self):
        """Ask the writer to finish remaining items and exit."""
        self._stop_event.set()

    def flush_and_stop(self, timeout=30):
        """Request stop, then block until the thread terminates."""
        self.request_stop()
        self.join(timeout=timeout)
        return dict(self.stats)

    # -- thread body ---------------------------------------------------------

    def run(self):
        while True:
            # Drain as long as there are items
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue

            self._write(item)

        # Final drain after stop is set
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                self._write(item)
            except queue.Empty:
                break

    def _write(self, item):
        filepath, data, fmt = item
        try:
            if fmt == "npy":
                np.save(filepath, data)
            elif fmt in ("jpg", "jpeg"):
                params = [cv2.IMWRITE_JPEG_QUALITY, self._jpg_quality]
                cv2.imwrite(filepath, data, params)
            elif fmt == "png":
                cv2.imwrite(filepath, data)
            else:
                np.save(filepath, data)
            self.stats["written"] += 1
        except Exception:
            self.stats["errors"] += 1


# ---------------------------------------------------------------------------
# Session recorder
# ---------------------------------------------------------------------------

class SessionRecorder:
    """Manages a single recording session on disk."""

    ALL_MODALITIES = ("RGB", "Depth", "IR", "Thermal")

    def __init__(self, base_dir, labels, config=None):
        """
        Parameters
        ----------
        base_dir : str or Path
            Top-level output directory (e.g. "data").
        labels : list[str]
            Ordered action labels for this session.
        config : dict, optional
            Full application config (used for save_format, jpg_quality).
        """
        self._cfg = config or {}
        self._labels = list(labels)
        self._current_label = labels[0] if labels else ""

        rec_cfg = self._cfg.get("recording", {})
        raw_sub = rec_cfg.get("raw_subdir", "raw")
        self._fmt = rec_cfg.get("save_format", {})
        jpg_q = rec_cfg.get("jpg_quality", 95)

        # Session directory
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = Path(base_dir) / raw_sub / f"session_{stamp}"

        # Create modality sub-directories
        self._dirs = {}
        for mod in self.ALL_MODALITIES:
            d = self._session_dir / mod
            d.mkdir(parents=True, exist_ok=True)
            self._dirs[mod] = d

        # Per-modality sequence counters
        self._seq = {m: 0 for m in self.ALL_MODALITIES}

        # In-memory timestamp log (flushed to CSV on finalise)
        self._timestamps = []

        # Breakpoint log
        self._breakpoints = []

        self._start_ns = time.time_ns()

        self._lock = threading.Lock()

        # Async writer
        self._writer = AsyncFrameWriter(maxsize=600, jpg_quality=jpg_q)
        self._writer.start()

    # ------------------------------------------------------------------ API

    @property
    def session_dir(self):
        return self._session_dir

    def write_frame(self, modality, frame, timestamp_ns):
        """Enqueue a frame for writing and record its timestamp."""
        with self._lock:
            seq = self._seq.get(modality, 0)
            self._seq[modality] = seq + 1
            label = self._current_label
            self._timestamps.append((seq, modality, timestamp_ns, label))

        fmt = self._resolve_format(modality)
        ext = self._ext_for_format(fmt)
        filename = f"frame_{seq:06d}{ext}"
        filepath = self._dirs[modality] / filename
        self._writer.enqueue(filepath, frame, fmt)

    def add_breakpoint(self, index, label_before, label_after, timestamp_ns):
        with self._lock:
            self._breakpoints.append({
                "index":        index,
                "label_before": label_before,
                "label_after":  label_after,
                "timestamp_ns": timestamp_ns,
            })
            self._current_label = label_after

    def finalize(self):
        """Write metadata, flush writer, and return session directory."""
        stop_ns = time.time_ns()
        stats = self._writer.flush_and_stop(timeout=30)
        self._write_timestamps_csv()
        self._write_session_meta(stop_ns, stats)
        return str(self._session_dir)

    def discard(self):
        """Cancel: stop writer and delete the entire session directory."""
        self._writer.flush_and_stop(timeout=5)
        shutil.rmtree(self._session_dir, ignore_errors=True)

    # -------------------------------------------------------- file helpers

    def _resolve_format(self, modality):
        return self._fmt.get(modality, "npy")

    @staticmethod
    def _ext_for_format(fmt):
        return {
            "npy":  ".npy",
            "jpg":  ".jpg",
            "jpeg": ".jpg",
            "png":  ".png",
        }.get(fmt, ".npy")

    # ---------------------------------------------------- metadata writers

    def _write_timestamps_csv(self):
        csv_path = self._session_dir / "timestamps.csv"
        with open(csv_path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["seq", "modality", "timestamp_ns", "label"])
            with self._lock:
                for row in self._timestamps:
                    writer.writerow(row)

    def _write_session_meta(self, stop_ns, writer_stats):
        meta = {
            "labels":              self._labels,
            "breakpoints":         self._breakpoints,
            "recording_start_ns":  self._start_ns,
            "recording_stop_ns":   stop_ns,
            "duration_s":          (stop_ns - self._start_ns) / 1.0e9,
            "frame_counts":        dict(self._seq),
            "writer_stats":        writer_stats,
            "save_formats":        {m: self._resolve_format(m) for m in self.ALL_MODALITIES},
        }
        meta_path = self._session_dir / "session_meta.json"
        with open(meta_path, "w") as fh:
            json.dump(meta, fh, indent=2)