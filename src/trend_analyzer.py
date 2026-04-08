"""
trend_analyzer.py - TikTok Research API でトレンドを分析するモジュール

TikTok Research APIで同ジャンルのバズ動画を収集し、
Gemini 2.5 Flashでタイトルの型・冒頭3秒の掴み・推奨ハッシュタグを分析して
スプレッドシートの trend_{genre} シートに追記する。

検索キーワード（ジャンル別）:
  zatugan:   「雑学」「豆知識」「知らなかった」「なぜ」
  setsuyaku: 「節約」「ポイ活」「NISA」「お金」
  lifehack:  「ライフハック」「時短」「便利」「裏技」

環境変数:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  GEMINI_API_KEY
"""

import os
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone

import requests
from google import genai
from spreadsheet import SpreadsheetManager

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
JST = timezone(timedelta(hours=9))

TIKTOK_RESEARCH_API = "https://open.tiktokapis.com/v2/research/video/query/"

GENRE_KEYWORDS = {
    "zatugan": ["雑学", "豆知識", "知らなかった", "なぜ"],
    "setsuyaku": ["節約", "ポイ活", "NISA", "お金"],
    "lifehack": ["ライフハック", "時短", "便利", "裏技"],
}


def analyze_trends(genre: str):
    """
    ジャンルのトレンドを収集・分析してスプレッドシートに追記する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
    """
    sheet = SpreadsheetManager(genre)
    gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    keywords = GENRE_KEYWORDS.get(genre, [])
    today = datetime.now(JST)
    since_date = (today - timedelta(days=14)).strftime("%Y%m%d")
    until_date = today.strftime("%Y%m%d")

    logger.info(f"Trend analysis started: genre={genre}, period={since_date}~{until_date}")

    # TikTok Research APIでバズ動画を収集
    videos = _fetch_tiktok_videos(keywords, since_date, until_date)

    if not videos:
        logger.warning(f"[{genre}] No videos fetched from TikTok Research API. Skipping analysis.")
        return

    logger.info(f"[{genre}] Fetched {len(videos)} videos")

    # Geminiで分析
    analysis = _analyze_with_gemini(gemini_client, genre, videos)

    # スプレッドシートに追記
    analysis["analyzed_at"] = today.strftime("%Y-%m-%d")
    sheet.append_trend_data(analysis)
    logger.info(f"[{genre}] Trend data saved")


def _get_access_token() -> str:
    """Client Credentials フローでアクセストークンを取得する"""
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise EnvironmentError("TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET is not set")

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to get TikTok access token: {data}")
    return token


def _fetch_tiktok_videos(
    keywords: list[str], since_date: str, until_date: str
) -> list[dict]:
    """
    TikTok Research APIでキーワード検索してバズ動画を取得する。
    APIが利用不可の場合は空リストを返す（処理を止めない）。
    """
    try:
        access_token = _get_access_token()
    except Exception as e:
        logger.warning(f"Failed to get TikTok access token: {e}. Skipping TikTok fetch.")
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    all_videos = []
    for keyword in keywords:
        try:
            payload = {
                "query": {
                    "and": [
                        {
                            "operation": "IN",
                            "field_name": "keyword",
                            "field_values": [keyword],
                        }
                    ]
                },
                "start_date": since_date,
                "end_date": until_date,
                "max_count": 20,
                "fields": "id,title,video_description,like_count,view_count,share_count,comment_count",
            }
            resp = requests.post(
                TIKTOK_RESEARCH_API,
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            videos = data.get("data", {}).get("videos", [])
            all_videos.extend(videos)
            logger.info(f"Fetched {len(videos)} videos for keyword: '{keyword}'")
        except Exception as e:
            logger.warning(f"TikTok Research API error for keyword '{keyword}': {e}")

    # バズスコア（like + share * 3）で降順ソートしてTOP20を返す
    all_videos.sort(
        key=lambda v: v.get("like_count", 0) + v.get("share_count", 0) * 3,
        reverse=True,
    )
    return all_videos[:20]


def _analyze_with_gemini(client, genre: str, videos: list[dict]) -> dict:
    """Geminiでバズ動画を分析してトレンドデータを返す"""
    video_texts = "\n".join(
        f"タイトル: {v.get('title', '')} | "
        f"説明: {v.get('video_description', '')[:50]} | "
        f"いいね: {v.get('like_count', 0)} | シェア: {v.get('share_count', 0)}"
        for v in videos[:20]
    )

    prompt = f"""以下はTikTokでバズった「{genre}」ジャンルの動画データです。

{video_texts}

このデータを分析して、以下のJSON形式で出力してください（JSONの外にテキストを書かないこと）:

{{
  "title_patterns": ["バズるタイトルの型（3つ）。例: 「数字+実は〇〇だった」「え？これ知らなかった！」"],
  "hook_style": "冒頭3秒で視聴者を引き付ける効果的な掴み方（1〜2文）",
  "recommended_hashtags": ["#推奨ハッシュタグ1", "#推奨ハッシュタグ2", "#推奨ハッシュタグ3", "#推奨ハッシュタグ4", "#推奨ハッシュタグ5"]
}}

ハッシュタグの条件:
- ちょうど5個
- 「#」を先頭に付けること
- このジャンルで実際に使われているハッシュタグ"""

    for attempt in range(3):
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(raw)
            required = ("title_patterns", "hook_style", "recommended_hashtags")
            if all(k in data for k in required):
                return data
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")

    logger.warning("Gemini trend analysis failed. Using defaults.")
    return {
        "title_patterns": [],
        "hook_style": "",
        "recommended_hashtags": [],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="トレンド分析")
    parser.add_argument("--genre", required=True, choices=["zatugan", "setsuyaku", "lifehack"])
    args = parser.parse_args()

    analyze_trends(args.genre)
