from __future__ import annotations

from pathlib import Path

from tools.pipeline.jobs.export_audio_ogg import process_audio_dir_for_ogg


def test_process_audio_dir_for_ogg_graceful(tmp_path: Path) -> None:
    in_dir = tmp_path / "audio_in"
    out_dir = tmp_path / "audio_out"
    in_dir.mkdir()

    # Create dummy wav file
    (in_dir / "sfx_laser.wav").write_bytes(b"RIFF....WAVEfmt ....data....")

    res = process_audio_dir_for_ogg(in_dir, out_dir)
    assert res["job"] == "export-audio-ogg"
    assert "ffmpeg_available" in res
    assert isinstance(res["converted_count"], int)
