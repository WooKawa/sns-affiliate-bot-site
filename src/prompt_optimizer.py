"""
prompt_optimizer.py - Geminiでプロンプト改善指示を自動生成するモジュール

analysisシートの最新行を読み込み、Gemini 2.5 Flashで
theme_generator・script_generator 向けの改善指示テキストを生成して
prompt_hintsシートに記録する。

theme_generator と script_generator はプロンプト生成時に
このシートを読み込み、自動的に改善指示を反映する設計。

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


def optimize_all():
    """全ジャンルの分析結果を読み込みプロンプト改善指示を生成する"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    week = _get_week_label()
    logger.info(f"Prompt optimization started: week={week}")

    for genre in GENRES:
        logger.info(f"=== Optimizing prompts for genre: {genre} ===")
        try:
            sheet = SpreadsheetManager(genre)
            analysis = sheet.get_latest_analysis()

            if not analysis:
                logger.warning(f"[{genre}] No analysis data found. Skipping.")
                continue

            theme_hint, script_hint = _generate_hints(client, genre, analysis)
            sheet.append_prompt_hints(week, theme_hint, script_hint)
            logger.info(f"[{genre}] Prompt hints saved for week: {week}")

        except Exception as e:
            logger.error(f"[{genre}] Prompt optimization failed: {e}")

    logger.info("Prompt optimization completed")


def _generate_hints(client, genre: str, analysis: dict) -> tuple[str, str]:
    """
    Geminiでtheme_generator用・script_generator用の改善指示を生成する。

    Returns:
        (theme_hint, script_hint): それぞれの改善指示テキスト
    """
    top_themes = analysis.get("top_themes", [])
    effective_hooks = analysis.get("effective_hooks", [])
    weak_patterns = analysis.get("weak_patterns", [])
    recommended_focus = analysis.get("recommended_focus", [])

    prompt = f"""あなたはSNSショート動画（ジャンル: {genre}）のコンテンツ改善アドバイザーです。

【先週の分析結果】
- 再生数が多い動画のテーマ: {', '.join(top_themes)}
- 効果的な冒頭・構成の特徴: {', '.join(effective_hooks)}
- パフォーマンスが低い動画のパターン: {', '.join(weak_patterns)}
- 来週の推奨フォーカス: {', '.join(recommended_focus)}

以上を踏まえて、以下のJSON形式で来週のコンテンツ生成改善指示を出力してください
（JSONの外にテキストを書かないこと）:

{{
  "theme_hint": "テーマ生成AIへの指示（100文字以内）。今週優先すべきテーマの方向性・避けるべきテーマを具体的に指示。",
  "script_hint": "台本生成AIへの指示（150文字以内）。効果的な冒頭の型・避けるべき表現・改善すべき構成を具体的に指示。"
}}

指示のポイント:
- 実際のパフォーマンスデータに基づいて具体的に書くこと
- AIが迷わず実行できる明確な指示にすること
- ネガティブな指示だけでなく「〇〇系を優先する」等ポジティブな指示も含めること"""

    for attempt in range(3):
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(raw)
            theme_hint = data.get("theme_hint", "")
            script_hint = data.get("script_hint", "")
            if theme_hint and script_hint:
                logger.info(f"[{genre}] theme_hint: {theme_hint[:50]}...")
                logger.info(f"[{genre}] script_hint: {script_hint[:50]}...")
                return theme_hint, script_hint
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")

    logger.warning(f"[{genre}] Failed to generate hints after 3 attempts. Using empty hints.")
    return "", ""


def _get_week_label() -> str:
    """今週のラベルを返す（例: 2026-W14）"""
    now = datetime.now(JST)
    return f"{now.strftime('%Y')}-W{now.strftime('%V')}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    optimize_all()
