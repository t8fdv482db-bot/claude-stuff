"""ffmpeg assembly: shot clips -> captions + label -> mixed, loudness-normalised MP4."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import ffmpeg

FPS = 30
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"


def avatar_clip(
    span_video: Path, offset: float, frames: int, size: tuple[int, int], out: Path, stage: Path | None = None
) -> Path:
    """Cut a shot from a lip-synced span video and frame it for the target aspect ratio."""
    w, h = size
    tail = f"fps={FPS},tpad=stop_mode=clone:stop_duration=3,setsar=1,format=yuv420p"
    if w > h:  # 16:9: presenter column on the left over the product 'stage'
        col_w = int(round(h * 9 / 16 / 2) * 2)
        x = int(w * 0.07)
        fc = (
            f"[0:v]{_cover(1080, 1920)},scale={col_w}:{h}:flags=lanczos,setsar=1[p];"
            f"[1:v]scale={w}:{h},setsar=1[s];[s][p]overlay={x}:0,{tail}[v]"
        )
        args = ["-ss", f"{offset:.3f}", "-i", span_video, "-loop", "1", "-i", stage, "-filter_complex", fc, "-map", "[v]"]
    elif w == h:  # 1:1: crop the upper part of the 9:16 frame (face sits in the upper third)
        vf = f"{_cover(1080, 1920)},crop=1080:1080:0:210,scale={w}:{h},{tail}"
        args = ["-ss", f"{offset:.3f}", "-i", span_video, "-vf", vf]
    else:
        args = ["-ss", f"{offset:.3f}", "-i", span_video, "-vf", f"{_cover(w, h)},{tail}"]
    ffmpeg.run([*args, "-frames:v", frames, "-r", FPS, *X264, "-an", out])
    return out


def still_clip(png: Path, frames: int, out: Path, fade_in: float = 0.3) -> Path:
    vf = f"fps={FPS},fade=t=in:st=0:d={fade_in},setsar=1,format=yuv420p"
    ffmpeg.run(["-loop", "1", "-i", png, "-vf", vf, "-frames:v", frames, "-r", FPS, *X264, "-an", out])
    return out


def _drawtext_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace("%", "\\%")


def finalize_video(
    clips: list[Path],
    size: tuple[int, int],
    audio: Path,
    out: Path,
    *,
    ass: Path | None,
    font_path: str,
    label: str | None,
) -> Path:
    """Concatenate shots, burn captions + disclosure label, mux the final audio."""
    w, h = size
    inputs: list = []
    for c in clips:
        inputs += ["-i", c]
    inputs += ["-i", audio]
    chain = "".join(f"[{i}:v]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0"
    if ass is not None:
        chain += f",subtitles=filename='{ffmpeg.escape_filter_path(ass)}':fontsdir='{ffmpeg.escape_filter_path(Path(font_path).parent)}'"
    if label:
        fs = max(18, int(min(w, h) * 0.026))
        chain += (
            f",drawtext=fontfile='{ffmpeg.escape_filter_path(font_path)}':text='{_drawtext_escape(label)}'"
            f":fontsize={fs}:fontcolor=white@0.92:box=1:boxcolor=black@0.45:boxborderw={fs // 2}"
            f":x={int(w * 0.04)}:y={int(h * 0.035)}"
        )
    chain += "[v]"
    ffmpeg.run(
        [
            *inputs,
            "-filter_complex", chain,
            "-map", "[v]", "-map", f"{len(clips)}:a",
            *X264, "-profile:v", "high", "-r", FPS,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart",
            out,
        ]
    )
    return out


def mix_audio(
    voice: Path,
    music: Path | None,
    total: float,
    body_end: float,
    out_dir: Path,
    *,
    music_db: float = -20.0,
    target_lufs: float = -14.0,
) -> Path:
    """Voice over a ducked music bed, then two-pass EBU R128 loudness normalisation."""
    premix = out_dir / "premix.wav"
    stereo = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    if music is None:
        fc = f"[0:a]{stereo},apad=whole_dur={total:.3f}[out]"
        ffmpeg.run(["-i", voice, "-filter_complex", fc, "-map", "[out]", "-t", f"{total:.3f}", premix])
    else:
        gain = 10 ** (music_db / 20)
        fade_out = max(0.0, total - 1.2)
        fc = (
            f"[0:a]{stereo},apad=whole_dur={total:.3f},asplit=2[v][sc];"
            f"[1:a]{stereo},loudnorm=I=-16:TP=-2,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
            # Bed sits low under the voice and lifts on the end card.
            f"volume='{gain:.4f}*if(gt(t,{body_end:.3f}),2.5,1)':eval=frame,"
            f"afade=t=in:d=0.4,afade=t=out:st={fade_out:.3f}:d=1.2[m];"
            "[m][sc]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=400[md];"
            "[v][md]amix=inputs=2:normalize=0:duration=first[out]"
        )
        ffmpeg.run(["-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex", fc, "-map", "[out]", "-t", f"{total:.3f}", premix])
    return loudnorm(premix, out_dir / "audio_final.wav", target_lufs)


def loudnorm(src: Path, dst: Path, target_lufs: float = -14.0, true_peak: float = -1.5, lra: float = 11.0) -> Path:
    base = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
    report = ffmpeg.run_capture_stderr(["-i", src, "-af", f"{base}:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", report, re.S)
    if not m:
        raise ffmpeg.FFmpegError("Could not parse loudnorm measurement")
    stats = json.loads(m.group(0))
    second = (
        f"{base}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true"
    )
    ffmpeg.run(["-i", src, "-af", second, "-ar", "48000", "-c:a", "pcm_s16le", dst])
    return dst


def measure_lufs(path: Path) -> float:
    report = ffmpeg.run_capture_stderr(["-i", path, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", report, re.S)
    return float(json.loads(m.group(0))["input_i"])


def thumbnail(video: Path, at: float, out: Path) -> Path:
    ffmpeg.run(["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-q:v", "2", out])
    return out
