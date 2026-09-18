"""Taiwanese Hokkien ASR — powered by MediaTek Breeze-ASR-26, tuned for low-VRAM GPUs."""

__version__ = "0.1.0"

from taigi_asr.segments import TimestampedSegment
from taigi_asr.km_wiki import KMWikiService

__all__ = ["TimestampedSegment", "KMWikiService", "__version__"]
