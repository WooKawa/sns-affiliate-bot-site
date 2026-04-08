"""
tiktok_uploader.py - TikTok Content Posting API v2 で動画を直接投稿するモジュール

認証方式: Client Credentials + Access Token（ジャンルごとに別アカウント）
投稿方式: Direct Post（ファイルアップロード）
エラー処理: 指数バックオフで最大3回リトライ

環境変数:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  TIKTOK_ACCESS_TOKEN_ZATUGAN   雑学アカウント用
  TIKTOK_ACCESS_TOKEN_SETSUYAKU 節約アカウント用
  TIKTOK_ACCESS_TOKEN_LIFEHACK  ライフハックアカウント用
"""

import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
VIDEO_PATH = "/tmp/output.mp4"
MAX_RETRIES = 3

GENRE_TO_TOKEN_ENV = {
    "zatugan": "TIKTOK_ACCESS_TOKEN_ZATUGAN",
    "setsuyaku": "TIKTOK_ACCESS_TOKEN_SETSUYAKU",
    "lifehack": "TIKTOK_ACCESS_TOKEN_LIFEHACK",
}


def upload_video(
    genre: str,
    title: str,
    description: str,
    video_path: str = VIDEO_PATH,
) -> str:
    """
    TikTok Content Posting API v2 で動画を投稿する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
        title: 動画タイトル（キャプションとして使用）
        description: 説明文・ハッシュタグ含む
        video_path: アップロードする動画ファイルパス

    Returns:
        TikTok動画ID（publish_id）
    """
    access_token = _get_access_token(genre)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    # キャプション = タイトル + 説明文（TikTokはdescriptionなし）
    # TikTokのキャプション上限: 2200文字
    caption = f"{title}\n\n{description}"[:2200]

    for attempt in range(MAX_RETRIES):
        try:
            video_id = _direct_post(headers, caption, video_path)
            logger.info(f"TikTok upload success: video_id={video_id}")
            return video_id
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                logger.warning(f"TikTok upload failed (attempt {attempt + 1}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"TikTok upload failed after {MAX_RETRIES} attempts: {e}")


def _get_access_token(genre: str) -> str:
    """ジャンルに対応するアクセストークンを取得する"""
    env_key = GENRE_TO_TOKEN_ENV.get(genre)
    if not env_key:
        raise ValueError(f"Unknown genre: '{genre}'")
    token = os.environ.get(env_key)
    if not token:
        raise EnvironmentError(f"Environment variable '{env_key}' is not set")
    return token


def _direct_post(headers: dict, caption: str, video_path: str) -> str:
    """
    TikTok Direct Post方式でファイルをアップロードする。
    Step 1: initialize → アップロードURLを取得
    Step 2: ファイルをアップロード
    Step 3: publish_idを返す
    """
    file_size = os.path.getsize(video_path)

    # Step 1: init
    init_payload = {
        "post_info": {
            "title": caption,
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 0,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        },
    }

    resp = requests.post(
        f"{TIKTOK_API_BASE}/post/publish/video/init/",
        headers=headers,
        json=init_payload,
        timeout=30,
    )
    resp.raise_for_status()
    init_data = resp.json()

    if init_data.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok init error: {init_data.get('error')}")

    upload_url = init_data["data"]["upload_url"]
    publish_id = init_data["data"]["publish_id"]
    logger.info(f"TikTok init success: publish_id={publish_id}")

    # Step 2: ファイルアップロード
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_headers = {
        "Content-Type": "video/mp4",
        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
        "Content-Length": str(file_size),
    }
    upload_resp = requests.put(
        upload_url,
        headers=upload_headers,
        data=video_bytes,
        timeout=300,
    )
    upload_resp.raise_for_status()
    logger.info("TikTok video file uploaded")

    return publish_id
