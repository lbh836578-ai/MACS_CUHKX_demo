"""
frame_packet.py
---------------
Lightweight value object that wraps a single captured frame together
with the metadata needed for synchronisation and recording.
"""


class FramePacket:
    """One captured frame plus its associated metadata."""

    __slots__ = ("modality", "data", "timestamp_ns", "seq")

    def __init__(self, modality, data, timestamp_ns, seq=0):
        """
        Parameters
        ----------
        modality : str
            One of "RGB", "Depth", "IR", "Thermal".
        data : numpy.ndarray or None
            Raw pixel data.
        timestamp_ns : int
            Host-clock capture timestamp from ``time.time_ns()``.
        seq : int
            Per-modality sequence counter (0-based).
        """
        self.modality = modality
        self.data = data
        self.timestamp_ns = timestamp_ns
        self.seq = seq

    def __repr__(self):
        shape = self.data.shape if self.data is not None else "None"
        return (
            f"FramePacket(mod={self.modality}, shape={shape}, "
            f"ts={self.timestamp_ns}, seq={self.seq})"
        )