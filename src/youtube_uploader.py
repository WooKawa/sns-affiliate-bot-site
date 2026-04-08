"""
youtube_uploader.py - YouTube Data API v3 で Shorts を予約投稿するモジュール（3ジャンル対応版）

既存の youtube-auto-bot/src/youtube_uploader.py をベースに改修。
変更点:
  - ジャンルごとに別アカウントのリフレッシュトークンを使用
  - カテゴリID: 27（教育）に変更
  - 予約投稿: 翌日 18:00 JST 固定（既存はランダム）
  - タイトル末尾の「 #Shorts」付与を保証（script_generatorで付与済みでも二重にならないよう考慮）
  - サムネイルアップロード機能は削除（Short専用のため不要）

環境変数:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN_ZATUGAN
  YOUTUBE_REFRESH_TOKEN_SETSUYAKU
  YOUTUBE_REFRESH_TOKEN_LIFEHACK
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

GENRE_TO_TOKEN_ENV = {
    "zatugan": "YOUTUBE_REFRESH_TOKEN_ZATUGAN",
    "setsuyaku": "YOUTUBE_REFRESH_TOKEN_SETSUYAKU",
    "lifehack": "YOUTUBE_REFRESH_TOKEN_LIFEHACK",
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
    credentials = _get_credentials(genre)
    youtube = build("youtube", "v3", credentials=credentials)

    publish_time_str = _get_publish_time()
    logger.info(f"Scheduled publish time: {publish_time_str}")

    # タイトル末尾に「 #Shorts」を確実に付与（重複チェック付き）
    if not title.endswith("#Shorts"):
        title = title.rstrip() + " #Shorts"

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": CATEGORY_ID,
            "defaultLanguage": "ja",
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


def _get_credentials(genre: str) -> Credentials:
    """
    ジャンルに対応するOAuth2情報からCredentialsを生成し、
    access_tokenを自動更新して返す。
    """
    token_env = GENRE_TO_TOKEN_ENV.get(genre)
    if not token_env:
        raise ValueError(f"Unknown genre: '{genre}'")

    refresh_token = os.environ.get(token_env)
    if not refresh_token:
        raise EnvironmentError(f"'{token_env}' is not set")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=YOUTUBE_SCOPES,
    )
    creds.refresh(Request())
    logger.info(f"YouTube credentials refreshed for genre: {genre}")
    return creds


def _get_publish_time() -> str:
    """翌日 18:00 JST をUTCのRFC3339形式で返す"""
    now_jst = datetime.now(JST)
    tomorrow_jst = now_jst + timedelta(days=1)
    publish_jst = tomorrow_jst.replace(hour=18, minute=0, second=0, microsecond=0)
    publish_utc = publish_jst.astimezone(timezone.utc)
    logger.info(f"Scheduled publish time (JST): {publish_jst.strftime('%Y-%m-%d %H:%M')}")
    return publish_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
