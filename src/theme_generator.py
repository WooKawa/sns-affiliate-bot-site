"""
theme_generator.py - ジャンル別テーマ自動生成モジュール

ジャンルごとに最適なSNS動画テーマを生成し、スプレッドシートに追記する。
過去テーマとの重複を避け、prompt_hintsシートの改善ヒントも反映する。

使用モデル: Gemini 2.5 Flash
環境変数: GEMINI_API_KEY
"""

import os
import logging
import argparse
from google import genai
from spreadsheet import SpreadsheetManager

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"

GENRE_PROMPTS = {
    "zatugan": {
        "desc": "雑学・知識系",
        "instruction": (
            "世界・日本・科学・歴史・動物・宇宙に関する「え、これ知ってた？」と驚かれるような"
            "雑学テーマを1つ提案してください。"
            "視聴者が思わず友達にシェアしたくなる、具体的で面白い事実や現象を選んでください。"
        ),
        "hook_style": "「え、これ知ってた？」「実は〇〇だった」「99%の人が知らない」",
    },
    "setsuyaku": {
        "desc": "節約・お金Tips",
        "instruction": (
            "節約・ポイ活・NISA・クレカ活用・保険見直しなどの「月○万節約できる」"
            "「知らないと損」系の実用的なお金Tipsテーマを1つ提案してください。"
            "初心者でも今すぐ実践できる、具体的で効果が高いものを選んでください。"
        ),
        "hook_style": "「月○万節約」「知らないと損」「今すぐやって」",
    },
    "lifehack": {
        "desc": "ライフハック・効率化",
        "instruction": (
            "スマホ裏技・時短術・仕事効率化・便利グッズ・神アプリなどの"
            "「これ神」「知らないと人生損」系のライフハックテーマを1つ提案してください。"
            "すぐに試せて効果が実感できる、具体的なテーマを選んでください。"
        ),
        "hook_style": "「これ神アプリ」「知らないと損」「やばすぎる裏技」",
    },
}


def generate_theme(genre: str) -> tuple[str, int]:
    """
    テーマを生成してスプレッドシートに追記する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'

    Returns:
        (theme, row_index): 生成テーマとスプレッドシートの行番号
    """
    sheet = SpreadsheetManager(genre)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    past_themes = sheet.get_all_themes()
    logger.info(f"Past themes count: {len(past_themes)}")

    if past_themes:
        themes_list = "\n".join(f"- {t}" for t in past_themes)
        past_themes_text = f"【過去に使用したテーマ一覧】\n{themes_list}"
    else:
        past_themes_text = "（まだテーマはありません）"

    genre_cfg = GENRE_PROMPTS[genre]

    # prompt_hintsシートから改善ヒントを読み込む
    hints = sheet.get_prompt_hints()
    hint_section = ""
    if hints and hints.get("theme_hint"):
        hint_section = f"\n【今週の改善指示】\n{hints['theme_hint']}\n"

    prompt = f"""{past_themes_text}
{hint_section}
あなたは{genre_cfg['desc']}のSNSショート動画クリエイターです。
{genre_cfg['instruction']}

フック例: {genre_cfg['hook_style']}

条件:
- 過去テーマと重複しないこと
- 30文字以内で具体的かつ興味を引くこと
- テーマ名のみを返すこと（説明・記号・番号は不要）
- TikTok・Instagram・YouTube Shortsで再生されやすいテーマにすること"""

    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    theme = response.text.strip()
    theme = theme.split("\n")[0].strip(" -・●▶「」")
    logger.info(f"Generated theme: '{theme}' (genre: {genre})")

    row_index = sheet.add_new_row(theme)
    return theme, row_index


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="テーマ自動生成")
    parser.add_argument("--genre", required=True, choices=["zatugan", "setsuyaku", "lifehack"])
    args = parser.parse_args()

    theme, row_index = generate_theme(args.genre)
    print(f"Generated: '{theme}' at row {row_index}")
