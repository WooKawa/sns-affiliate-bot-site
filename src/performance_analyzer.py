"""
performance_analyzer.py - analyticsシートのデータをGeminiで分析するモジュール

直近4週分のパフォーマンスデータを読み込み、Gemini 2.5 Flashで分析して
スプレッドシートの「analysis」シートに結果を記録する。

分析内容:
  - TOP5動画の共通点（タイトル・テーマ・冒頭構成）
  - CVR（プロフ遷移）が高い動画の特徴
  - 完走率が低い動画の問題点
  - ジャンル別・媒体別のパフォーマンス差

環境変数: GEMINI_API_KEY
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

from google import genai
from spreadsheet import SpreadsheetManager

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
GENRES = ("zatugan", "setsuyaku", "lifehack")
JST = timezone(timedelta(hours=9))


def analyze_all():
    """全ジャンルのパフォーマンスデータを分析してanalysisシートに記録する"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    week = _get_week_label()
    logger.info(f"Performance analysis started: week={week}")

    for genre in GENRES:
        logger.info(f"=== Analyzing genre: {genre} ===")
        try:
            sheet = SpreadsheetManager(genre)
            records = sheet.get_analytics_recent(weeks=4)

            if not records:
                logger.warning(f"[{genre}] No analytics data found. Skipping.")
                continue

            analysis = _analyze_with_gemini(client, genre, records)
            sheet.append_analysis(week, analysis)
            logger.info(f"[{genre}] Analysis saved for week: {week}")

        except Exception as e:
            logger.error(f"[{genre}] Analysis failed: {e}")

    logger.info("Performance analysis completed")


def _analyze_with_gemini(client, genre: str, records: list[dict]) -> dict:
    """Geminiでパフォーマンスデータを分析してJSON形式で返す"""
    # データを読みやすい形式に整形
    records_text = "\n".join(
        f"- 媒体:{r['platform']} ID:{r['video_id']} "
        f"再生:{r['views']} 完走率:{r['completion_rate']}% "
        f"CVR:{r['cvr']}% いいね:{r['likes']}"
        for r in sorted(records, key=lambda x: int(x.get("views", 0) or 0), reverse=True)[:30]
    )

    prompt = f"""以下はSNSショート動画（ジャンル: {genre}）の直近4週間のパフォーマンスデータです。

{records_text}

このデータを分析して、以下のJSON形式で出力してください（JSONの外にテキストを書かないこと）:

{{
  "top_themes": ["再生数が多い動画の共通テーマや特徴（3つ）"],
  "effective_hooks": ["CVRや完走率が高い動画の冒頭・構成の特徴（3つ）"],
  "weak_patterns": ["完走率や再生数が低い動画に見られる問題パターン（3つ）"],
  "recommended_focus": ["来週のコンテンツ生成で優先すべき方向性（3つ）"]
}}

分析のポイント:
- 再生数TOP5の共通点（タイトルのパターン・テーマの傾向）
- 完走率が高い動画と低い動画の違い
- 媒体別（instagram/youtube）のパフォーマンス差
- 来週改善すべき最重要ポイント"""

    for attempt in range(3):
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(raw)
            required = ("top_themes", "effective_hooks", "weak_patterns", "recommended_focus")
            if all(k in data for k in required):
                return data
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")

    # フォールバック
    logger.warning("Gemini analysis failed after 3 attempts. Using empty analysis.")
    return {
        "top_themes": [],
        "effective_hooks": [],
        "weak_patterns": [],
        "recommended_focus": [],
    }


def _get_week_label() -> str:
    """今週のラベルを返す（例: 2026-W14）"""
    now = datetime.now(JST)
    return f"{now.strftime('%Y')}-W{now.strftime('%V')}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    analyze_all()
