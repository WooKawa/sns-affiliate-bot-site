"""
youtube_uploader.py - YouTube Data API v3 で Shorts を予約投稿するモジュール（3ジャンル対応版）

既存の youtube-auto-bot/src/youtube_uploader.py をベースに改修。
変更点:
  - 全チャンネル共通の YOUTUBE_REFRESH_TOKEN を使用（同一Googleアカウント運用対応）
  - ジャンルごとのチャンネルIDを環境変数で指定（YOUTUBE_CHANNEL_ID_*）
  - カテゴリID: 27（教育）に変更
  - 予約投稿: 翌日 18:00 JST 固定
  - タイトル末尾の「 #Shorts」付与を保証
  - サムネイルアップロード機能は削除（Short専用のため不要）

環境変数:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN            ← 全チャンネル共通（同一Googleアカウント）
  YOUTUBE_CHANNEL_ID_ZATUGAN       ← 雑学チャンネルID
  YOUTUBE_CHANNEL_ID_SETSUYAKU     ← 節約チャンネルID
  YOUTUBE_CHANNEL_ID_LIFEHACK      ← ライフハックチャンネルID
"""

import os
import logging
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CATEGORY_ID = "27"  # 教育

GENRE_TO_CHANNEL_ID_ENV = {
    "zatugan":   "YOUTUBE_CHANNEL_ID_ZATUGAN",
    "setsuyaku": "YOUTUBE_CHANNEL_ID_SETSUYAKU",
    "lifehack":  "YOUTUBE_CHANNEL_ID_LIFEHACK",
}


def upload_video(
    genre: str,
    video_path: str,
    title: str,
    description: str,
) -> str:
    """
    動画をYouTube Shortsとして翌日18:00 JSTに予約投稿する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
        video_path: アップロードする動画ファイルパス
        title: 動画タイトル（末尾に「 #Shorts」を確実に付与）
        description: 動画説明文

    Returns:
        YouTube動画ID
    """
    credentials = _get_credentials()
    youtube = build("youtube", "v3", credentials=credentials)

    publish_time_str = _get_publish_time()
    logger.info(f"Scheduled publish time: {publish_time_str}")

    # タイトル末尾に「 #Shorts」を確実に付与（重複チェック付き）
    if not title.endswith("#Shorts"):
        title = title.rstrip() + " #Shorts"

    # ジャンルに対応するチャンネルIDを取得
    channel_id_env = GENRE_TO_CHANNEL_ID_ENV.get(genre)
    channel_id = os.environ.get(channel_id_env, "") if channel_id_env else ""
    if channel_id:
        logger.info(f"Target channel ID: {channel_id}")
    else:
        logger.warning(f"YOUTUBE_CHANNEL_ID_{genre.upper()} not set. Using default channel.")

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": CATEGORY_ID,
            "defaultLanguage": "ja",
            **({"channelId": channel_id} if channel_id else {}),
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_time_str,
            "selfDeclaredMadeForKids": False,
        },
    }

    logger.info(f"Uploading YouTube Shorts: '{title}'")
    media = MediaFileUpload(
        video_path,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            logger.info(f"Upload progress: {pct}%")

    video_id = response["id"]
    logger.info(f"YouTube upload complete! Video ID: {video_id}")
    return video_id


def _get_credentials() -> Credentials:
    """
    共通のOAuth2情報からCredentialsを生成し、access_tokenを自動更新して返す。
    全チャンネルが同一Googleアカウントで運用されている前提。
    """
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not refresh_token:
        raise EnvironmentError("'YOUTUBE_REFRESH_TOKEN' is not set")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=YOUTUBE_SCOPES,
    )
    creds.refresh(Request())
    logger.info("YouTube credentials refreshed (shared account)")
    return creds


def _get_publish_time() -> str:
    """翌日 18:00 JST をUTCのRFC3339形式で返す"""
    now_jst = datetime.now(JST)
    tomorrow_jst = now_jst + timedelta(days=1)
    publish_jst = tomorrow_jst.replace(hour=18, minute=0, second=0, microsecond=0)
    publish_utc = publish_jst.astimezone(timezone.utc)
    logger.info(f"Scheduled publish time (JST): {publish_jst.strftime('%Y-%m-%d %H:%M')}")
    return publish_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
