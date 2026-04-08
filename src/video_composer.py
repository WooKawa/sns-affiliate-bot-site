"""
video_composer.py - 動画合成・字幕焼き込みモジュール（40秒Short専用版）

処理フロー:
  1. Whisper small で音声転写 → タイムスタンプ付きセグメント取得
  2. MoviePy で背景クリップをリサイズ・クロップ・連結
  3. ASS形式の字幕ファイルを生成
  4. FFmpeg で 音声+背景動画+字幕 を合成して出力

出力仕様: 1080x1920 / 30fps / libx264 / MP4
字幕:     下部中央 / NotoSansCJK-Bold / size48 / 白文字黒縁2px
"""

import os
import json
import logging
import subprocess
from pathlib import Path

import whisper
from moviepy.editor import VideoFileClip, concatenate_videoclips

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
FPS = 30
FONT_DIR = "/usr/share/fonts/truetype/noto"
FONT_NAME = "Noto Sans CJK JP Bold"
WHISPER_MODEL = "small"


def compose_video(
    video_clips: list[dict],
    audio_path: str,
    script: str,
    output_path: str = "/tmp/output.mp4",
) -> str:
    """
    背景動画・音声・字幕を合成して最終動画を生成する。

    Args:
        video_clips: [{"path": str, "duration": int}, ...]
        audio_path: ナレーション音声ファイルパス
        script: ナレーション台本テキスト（字幕の参照用）
        output_path: 出力先パス

    Returns:
        output_path
    """
    # Step 1: 音声の長さを取得
    audio_duration = _get_audio_duration(audio_path)
    logger.info(f"Audio duration: {audio_duration:.1f}s")

    # Step 2: 背景動画を合成（リサイズ・連結・ループ）
    bg_video_path = "/tmp/bg_combined.mp4"
    _prepare_background(video_clips, audio_duration, bg_video_path)

    # Step 3: Whisperで音声転写
    logger.info(f"Transcribing with Whisper model: {WHISPER_MODEL}")
    segments = _transcribe(audio_path)
    logger.info(f"Whisper segments: {len(segments)}")

    # Step 4: ASSファイル生成
    subtitle_path = "/tmp/subtitles.ass"
    _generate_ass(segments, subtitle_path)

    # Step 5: FFmpegで最終合成
    _ffmpeg_compose(bg_video_path, audio_path, subtitle_path, output_path)

    logger.info(f"Video composed: {output_path}")
    return output_path


# ──────────────────────────────────────────────
# 内部処理
# ──────────────────────────────────────────────

def _get_audio_duration(audio_path: str) -> float:
    """ffprobeで音声の長さを取得"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", audio_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _prepare_background(
    video_clips: list[dict], target_duration: float, output_path: str
):
    """背景動画をリサイズ・クロップ・連結してtarget_durationに合わせる"""
    processed = []

    for i, clip_info in enumerate(video_clips):
        src_path = clip_info["path"]
        clip_duration = float(clip_info["duration"])
        dst_path = f"/tmp/clip_proc_{i:02d}.mp4"
        _resize_crop_clip(src_path, clip_duration, dst_path)
        processed.append(dst_path)

    # concat list作成
    list_path = "/tmp/concat_list.txt"
    with open(list_path, "w") as f:
        for p in processed:
            f.write(f"file '{p}'\n")

    # 連結
    concat_path = "/tmp/bg_concat.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-r", str(FPS),
            concat_path,
        ],
        check=True,
        capture_output=True,
    )

    # ループして target_duration に切り揃え
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", concat_path,
            "-t", str(target_duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-r", str(FPS),
            "-an",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    logger.info(f"Background video prepared: {output_path}")


def _resize_crop_clip(src: str, duration: float, dst: str):
    """MoviePyでクリップを1080x1920にリサイズ・クロップ"""
    try:
        clip = VideoFileClip(src, audio=False)

        target_ratio = OUTPUT_WIDTH / OUTPUT_HEIGHT
        current_ratio = clip.w / clip.h

        if current_ratio > target_ratio:
            new_w = int(clip.h * target_ratio)
            x_center = clip.w / 2
            clip = clip.crop(x1=x_center - new_w / 2, x2=x_center + new_w / 2)
        elif current_ratio < target_ratio:
            new_h = int(clip.w / target_ratio)
            y_center = clip.h / 2
            clip = clip.crop(y1=y_center - new_h / 2, y2=y_center + new_h / 2)

        clip = clip.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT))

        if clip.duration < duration:
            n = int(duration / clip.duration) + 1
            clip = concatenate_videoclips([clip] * n)

        clip = clip.subclip(0, min(duration, clip.duration))
        clip.write_videofile(
            dst, fps=FPS, codec="libx264", preset="fast", audio=False, logger=None,
        )
        clip.close()

    except Exception as e:
        logger.warning(f"MoviePy failed for {src}: {e}. Falling back to FFmpeg.")
        _ffmpeg_resize_crop(src, duration, dst)


def _ffmpeg_resize_crop(src: str, duration: float, dst: str):
    """FFmpegによるリサイズ・クロップ（MoviePyのフォールバック）"""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-vf", (
                f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
            ),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-r", str(FPS),
            "-an",
            dst,
        ],
        check=True,
        capture_output=True,
    )


def _transcribe(audio_path: str) -> list[dict]:
    """Whisper smallで音声転写してセグメント（start/end/text）を返す"""
    model = whisper.load_model(WHISPER_MODEL)
    result = model.transcribe(audio_path, language="ja", verbose=False)
    return [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
        for seg in result.get("segments", [])
        if seg["text"].strip()
    ]


def _generate_ass(segments: list[dict], output_path: str):
    """
    FFmpeg用ASSファイルを生成する。
    フォント: Noto Sans CJK JP Bold / size48 / 白文字・黒縁2px
    位置: 下部中央（Alignment=2）
    """
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUTPUT_WIDTH}
PlayResY: {OUTPUT_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},48,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

    def _fmt_time(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        cs = int((s % 1) * 100)
        return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

    lines = [ass_header]
    for seg in segments:
        start = _fmt_time(seg["start"])
        end = _fmt_time(seg["end"])
        text = seg["text"].replace("\n", "\\N").replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"ASS subtitle generated: {output_path} ({len(segments)} segments)")


def _ffmpeg_compose(bg_video: str, audio: str, subtitle: str, output: str):
    """FFmpegで背景動画・音声・字幕を合成して最終動画を出力"""
    cmd = [
        "ffmpeg", "-y",
        "-i", bg_video,
        "-i", audio,
        "-vf", f"ass={subtitle}:fontsdir={FONT_DIR}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-shortest",
        output,
    ]
    logger.info("Running FFmpeg final composition...")
    subprocess.run(cmd, check=True)
    logger.info(f"Final video: {output}")
