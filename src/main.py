"""
main.py - SNS自動投稿システム メイン実行スクリプト（Short専用・3媒体同時投稿）

実行順序:
  1. theme_generator   テーマ生成・スプレッドシート追記
  2. spreadsheet       pending行取得
  3. affiliate_selector 案件マスターからアフィリ自動選定
  4. script_generator  台本・タイトル・説明文・ハッシュタグ生成
  5. tts               音声合成 → /tmp/narration.mp3
  6. video_fetcher     Pexels素材取得 → /tmp/video_XX.mp4
  7. video_composer    動画合成・字幕焼き込み → /tmp/output.mp4
  8. 3媒体並列アップロード（TikTok・Instagram・YouTube）
  9. ステータスを「完了」に更新
  10. /tmp/ 一時ファイル全削除

使用方法:
  python src/main.py --genre zatugan
  python src/main.py --genre setsuyaku
  python src/main.py --genre lifehack
"""

import os
import sys
import glob
import logging
import argparse
import concurrent.futures
from pathlib import Path

# src/ 直下を実行するためパスを通す
sys.path.insert(0, str(Path(__file__).parent))

import theme_generator
import affiliate_selector
import script_generator
import tts
import video_fetcher
import video_composer
import tiktok_uploader
import instagram_uploader
import youtube_uploader
from spreadsheet import SpreadsheetManager

# ──────────────────────────────────────────────
# ログ設定
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

VIDEO_PATH = "/tmp/output.mp4"
AUDIO_PATH = "/tmp/narration.mp3"


def run(genre: str):
    """
    指定ジャンルの動画を生成して3媒体に同時投稿する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
    """
    logger.info(f"=== SNS Auto-Post Start: genre={genre} ===")

    sheet = SpreadsheetManager(genre)
    row_index = None

    try:
        # ──────────────────────────────────────
        # Step 1: テーマ生成
        # ──────────────────────────────────────
        logger.info("[Step 1] Generating theme...")
        theme, row_index = theme_generator.generate_theme(genre)
        logger.info(f"Theme: '{theme}' at row {row_index}")

        # ──────────────────────────────────────
        # Step 2: pending行取得（Step 1で追加した行）
        # ──────────────────────────────────────
        logger.info("[Step 2] Getting pending row...")
        pending = sheet.get_pending_row()
        if pending is None:
            raise RuntimeError("No pending row found after theme generation")
        row_index, theme = pending
        sheet.update_status(row_index, "処理中")

        # ──────────────────────────────────────
        # Step 3: アフィリエイト案件自動選定
        # ──────────────────────────────────────
        logger.info("[Step 3] Selecting affiliate...")
        affili_result = affiliate_selector.select_affiliate(genre, theme, row_index)
        product_name = affili_result.get("product_name", "")
        logger.info(f"Affiliate product: '{product_name}'")

        # ──────────────────────────────────────
        # Step 4: 台本・メタデータ生成
        # ──────────────────────────────────────
        logger.info("[Step 4] Generating script...")
        trend_data = sheet.get_latest_trend()
        prompt_hints = sheet.get_prompt_hints()
        script_data = script_generator.generate_script(
            genre=genre,
            theme=theme,
            product_name=product_name,
            trend_data=trend_data,
            prompt_hints=prompt_hints,
        )
        sheet.update_script_data(row_index, script_data)
        logger.info(f"Title: {script_data['title']}")

        # ──────────────────────────────────────
        # Step 5: 音声合成
        # ──────────────────────────────────────
        logger.info("[Step 5] Generating audio...")
        tts.synthesize_speech(script_data["script"])

        # ──────────────────────────────────────
        # Step 6: 背景動画取得
        # ──────────────────────────────────────
        logger.info("[Step 6] Fetching background videos...")
        downloaded_paths = video_fetcher.fetch_videos(script_data["scenes"], video_type="short")
        # video_composerが期待する辞書形式に変換
        scenes = script_data.get("scenes", [{}])
        video_clips = [
            {"path": p, "duration": scenes[i].get("duration", 20) if i < len(scenes) else 20}
            for i, p in enumerate(downloaded_paths)
        ]

        # ──────────────────────────────────────
        # Step 7: 動画合成・字幕焼き込み
        # ──────────────────────────────────────
        logger.info("[Step 7] Composing video...")
        video_composer.compose_video(
            video_clips=video_clips,
            audio_path=AUDIO_PATH,
            script=script_data["script"],
            output_path=VIDEO_PATH,
        )

        # ──────────────────────────────────────
        # Step 8: 3媒体並列アップロード
        # ──────────────────────────────────────
        logger.info("[Step 8] Uploading to 3 platforms in parallel...")
        title = script_data["title"]
        description = script_data["description"]

        upload_results = _upload_parallel(genre, title, description, VIDEO_PATH)

        # 動画IDをスプレッドシートに記録
        for platform, video_id in upload_results.items():
            if video_id:
                sheet.update_platform_id(row_index, platform, video_id)
                logger.info(f"{platform} upload success: {video_id}")
            else:
                logger.warning(f"{platform} upload failed or skipped")

        # ──────────────────────────────────────
        # Step 9: ステータス更新
        # ──────────────────────────────────────
        sheet.update_status(row_index, "完了")
        logger.info(f"=== Completed: row={row_index}, theme='{theme}' ===")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        if row_index:
            try:
                sheet.update_status(row_index, "エラー", error_msg=str(e))
            except Exception as inner_e:
                logger.error(f"Failed to update error status: {inner_e}")
        raise

    finally:
        # Step 10: /tmp/ 一時ファイルを全削除
        _cleanup_tmp()


def _upload_parallel(
    genre: str, title: str, description: str, video_path: str
) -> dict[str, str | None]:
    """
    TikTok・Instagram・YouTube に並列でアップロードする。

    Returns:
        {"tiktok": id_or_None, "instagram": id_or_None, "youtube": id_or_None}
    """
    results = {"tiktok": None, "instagram": None, "youtube": None}

    def upload_tiktok():
        return tiktok_uploader.upload_video(genre, title, description, video_path)

    def upload_instagram():
        return instagram_uploader.upload_video(genre, description, video_path)

    def upload_youtube():
        return youtube_uploader.upload_video(genre, video_path, title, description)

    tasks = {
        "tiktok": upload_tiktok,
        "instagram": upload_instagram,
        "youtube": upload_youtube,
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fn): platform
            for platform, fn in tasks.items()
        }
        for future in concurrent.futures.as_completed(futures):
            platform = futures[future]
            try:
                results[platform] = future.result()
            except Exception as e:
                logger.error(f"[{platform}] Upload error: {e}")
                results[platform] = None

    return results


def _cleanup_tmp():
    """/tmp/ 以下の一時ファイルを削除する"""
    patterns = [
        "/tmp/narration.mp3",
        "/tmp/output.mp4",
        "/tmp/bg_combined.mp4",
        "/tmp/bg_concat.mp4",
        "/tmp/concat_list.txt",
        "/tmp/subtitles.ass",
        "/tmp/video_*.mp4",
        "/tmp/clip_proc_*.mp4",
    ]
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                os.remove(path)
                logger.debug(f"Deleted: {path}")
            except OSError:
                pass
    logger.info("Temp files cleaned up")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNS自動投稿システム")
    parser.add_argument(
        "--genre",
        required=True,
        choices=["zatugan", "setsuyaku", "lifehack"],
        help="投稿するジャンル",
    )
    args = parser.parse_args()
    run(args.genre)
