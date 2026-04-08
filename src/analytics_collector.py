"""
analytics_collector.py - 各プラットフォームのパフォーマンスデータ収集モジュール

収集対象（過去7日分）:
  [TikTok]    暫定スキップ（TikTok Research APIは自社アカウントの分析不可のため手動確認）
  [Instagram] Meta Graph API → Reelsの再生数・リーチ・いいね・プロフアクセス数
  [YouTube]   YouTube Analytics API → Shortsの再生数・完了率・クリック率

全ジャンル（zatugan / setsuyaku / lifehack）× 全媒体のデータを収集し、
各ジャンルのスプレッドシートの「analytics」シートに追記する。

環境変数:
  INSTAGRAM_ACCESS_TOKEN_{GENRE}
  INSTAGRAM_USER_ID_{GENRE}
  YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN_{GENRE}
  GOOGLE_SERVICE_ACCOUNT_JSON
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from spreadsheet import SpreadsheetManager

logger = logging.getLogger(__name__)

GENRES = ("zatugan", "setsuyaku", "lifehack")
JST = timezone(timedelta(hours=9))

INSTAGRAM_GENRE_ENV = {
    "zatugan": ("INSTAGRAM_ACCESS_TOKEN_ZATUGAN", "INSTAGRAM_USER_ID_ZATUGAN"),
    "setsuyaku": ("INSTAGRAM_ACCESS_TOKEN_SETSUYAKU", "INSTAGRAM_USER_ID_SETSUYAKU"),
    "lifehack": ("INSTAGRAM_ACCESS_TOKEN_LIFEHACK", "INSTAGRAM_USER_ID_LIFEHACK"),
}
YOUTUBE_TOKEN_ENV = {
    "zatugan": "YOUTUBE_REFRESH_TOKEN_ZATUGAN",
    "setsuyaku": "YOUTUBE_REFRESH_TOKEN_SETSUYAKU",
    "lifehack": "YOUTUBE_REFRESH_TOKEN_LIFEHACK",
}
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


def collect_all():
    """全ジャンルのパフォーマンスデータを収集してspreadsheetに追記する"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    since_date = (datetime.now(JST) - timedelta(days=7)).strftime("%Y-%m-%d")

    logger.info(f"Analytics collection started: {since_date} → {today}")

    for genre in GENRES:
        logger.info(f"=== Collecting for genre: {genre} ===")
        sheet = SpreadsheetManager(genre)

        # TikTok: 暫定スキップ
        logger.warning(
            f"[TikTok/{genre}] Analytics collection is SKIPPED. "
            "TikTok Research API cannot access own account metrics. Please check manually."
        )

        # Instagram
        try:
            ig_records = _collect_instagram(genre, since_date)
            for rec in ig_records:
                rec["genre"] = genre
                rec["date"] = today
                sheet.append_analytics(rec)
            logger.info(f"[Instagram/{genre}] Collected {len(ig_records)} records")
        except Exception as e:
            logger.error(f"[Instagram/{genre}] Collection failed: {e}")

        # YouTube
        try:
            yt_records = _collect_youtube(genre, since_date, today)
            for rec in yt_records:
                rec["genre"] = genre
                rec["date"] = today
                sheet.append_analytics(rec)
            logger.info(f"[YouTube/{genre}] Collected {len(yt_records)} records")
        except Exception as e:
            logger.error(f"[YouTube/{genre}] Collection failed: {e}")

    logger.info("Analytics collection completed")


# ──────────────────────────────────────────────
# Instagram 収集
# ──────────────────────────────────────────────

def _collect_instagram(genre: str, since_date: str) -> list[dict]:
    """Meta Graph APIからReelsのメトリクスを取得する"""
    token_env, user_id_env = INSTAGRAM_GENRE_ENV[genre]
    access_token = os.environ.get(token_env)
    user_id = os.environ.get(user_id_env)
    if not access_token or not user_id:
        logger.warning(f"[Instagram/{genre}] Token or user_id not set. Skipping.")
        return []

    # 投稿一覧を取得
    media_ids = _get_instagram_media_ids(user_id, access_token)
    if not media_ids:
        return []

    records = []
    for media_id in media_ids[:50]:  # 直近50件まで
        try:
            insights = _get_instagram_insights(media_id, access_token)
            if insights:
                records.append({
                    "platform": "instagram",
                    "video_id": media_id,
                    "views": insights.get("plays", 0),
                    "completion_rate": 0,  # Instagram APIは完了率未提供
                    "cvr": 0,
                    "likes": insights.get("likes", 0),
                    "comments": insights.get("comments", 0),
                    "shares": insights.get("shares", 0),
                })
        except Exception as e:
            logger.warning(f"[Instagram] Failed to get insights for {media_id}: {e}")

    return records


def _get_instagram_media_ids(user_id: str, access_token: str) -> list[str]:
    """ユーザーの最新メディアIDリストを取得する"""
    url = f"{GRAPH_API_BASE}/{user_id}/media"
    params = {
        "fields": "id,media_type,timestamp",
        "access_token": access_token,
        "limit": 50,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [
        item["id"] for item in data.get("data", [])
        if item.get("media_type") in ("VIDEO", "REELS")
    ]


def _get_instagram_insights(media_id: str, access_token: str) -> dict:
    """特定メディアのインサイトを取得する"""
    url = f"{GRAPH_API_BASE}/{media_id}/insights"
    params = {
        "metric": "plays,likes,comments,shares,reach",
        "access_token": access_token,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for item in data.get("data", []):
        result[item["name"]] = item.get("values", [{}])[0].get("value", 0)
    return result


# ──────────────────────────────────────────────
# YouTube 収集
# ──────────────────────────────────────────────

def _collect_youtube(genre: str, since_date: str, until_date: str) -> list[dict]:
    """YouTube Analytics APIからShortsのメトリクスを取得する"""
    token_env = YOUTUBE_TOKEN_ENV.get(genre)
    refresh_token = os.environ.get(token_env)
    if not refresh_token:
        logger.warning(f"[YouTube/{genre}] Refresh token not set. Skipping.")
        return []

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=YOUTUBE_SCOPES,
    )
    creds.refresh(Request())

    youtube = build("youtube", "v3", credentials=creds)
    yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    # チャンネルIDを取得
    channel_resp = youtube.channels().list(part="id", mine=True).execute()
    channels = channel_resp.get("items", [])
    if not channels:
        logger.warning(f"[YouTube/{genre}] No channel found.")
        return []
    channel_id = channels[0]["id"]

    # Analytics APIでメトリクスを取得
    try:
        analytics_resp = yt_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=since_date,
            endDate=until_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments",
            dimensions="video",
            sort="-views",
            maxResults=50,
        ).execute()
    except Exception as e:
        logger.warning(f"[YouTube/{genre}] Analytics API error: {e}")
        return []

    rows = analytics_resp.get("rows", [])
    records = []
    for row in rows:
        video_id = row[0]
        views = row[1]
        estimated_minutes = row[2]
        avg_duration = row[3]
        likes = row[4]
        comments = row[5]

        # 完了率の推定（avg_duration / 40秒 * 100）
        completion_rate = round(min(avg_duration / 40 * 100, 100), 1) if avg_duration else 0

        records.append({
            "platform": "youtube",
            "video_id": video_id,
            "views": int(views),
            "completion_rate": completion_rate,
            "cvr": 0,
            "likes": int(likes),
            "comments": int(comments),
            "shares": 0,
        })

    return records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    collect_all()
