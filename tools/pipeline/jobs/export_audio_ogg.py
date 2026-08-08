"""Conversion Factory job: Convert WAV audio files to streaming Ogg Vorbis (.ogg) for Godot 4.x.

Checks for ffmpeg or uses standard WAV fallback for spatial SFX in Godot.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def convert_wav_to_ogg(wav_path: Path, ogg_path: Path) -> bool:
    """Convert a single WAV file to Ogg Vorbis format using ffmpeg if available."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(wav_path), "-c:a", "libvorbis", "-qscale:a", "5", str(ogg_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0 and ogg_path.exists() and ogg_path.stat().st_size > 0
    except Exception:
        return False


def process_audio_dir_for_ogg(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Batch convert all WAV audio files in input_dir to Ogg Vorbis in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_files = list(input_dir.glob("*.wav"))
    converted = []
    skipped = []

    has_ffmpeg = bool(shutil.which("ffmpeg"))

    for wav in wav_files:
        ogg_dest = output_dir / f"{wav.stem}.ogg"
        if has_ffmpeg and convert_wav_to_ogg(wav, ogg_dest):
            converted.append({
                "wav": str(wav),
                "ogg": str(ogg_dest),
                "bytes": ogg_dest.stat().st_size,
            })
        else:
            skipped.append(str(wav))

    return {
        "job": "export-audio-ogg",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "ffmpeg_available": has_ffmpeg,
        "converted_count": len(converted),
        "converted": converted,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "note": "Godot consumes native WAV files directly for positional SFX when Ogg conversion is unavailable."
    }
