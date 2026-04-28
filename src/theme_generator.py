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
            "世界・日本・科学・歴史・動物・宇宙に関する雑学テーマを1つ提案してください。"
            "以下の型を意識して、視聴者が思わずシェアしたくなるテーマを選んでください。\n"
            "・「え、これ知ってた？」「実は〇〇だった」系の驚き系（約40%）\n"
            "・「学校で教えてくれなかった〇〇」「〇〇の本当の理由」系の暴露・裏側系（約30%）\n"
            "・「99%の人が勘違いしてる〇〇」「常識を覆す〇〇の真実」系の常識破壊系（約30%）"
        ),
        "hook_style": "「え、これ知ってた？」「学校で教えてくれなかった」「99%の人が勘違いしてる」「〇〇の闇が深すぎる」",
    },
    "setsuyaku": {
        "desc": "節約・お金Tips",
        "instruction": (
            "節約・ポイ活・NISA・クレカ活用・保険見直しなどのお金テーマを1つ提案してください。"
            "以下の型を意識して、視聴者が「自分ごと」として見てしまうテーマを選んでください。\n"
            "・「月○万節約できる」「知らないと損」系の実用Tips（約40%）\n"
            "・「銀行・保険会社が教えない」「CMで言えない」系の暴露系（約30%）\n"
            "・「まだ〇〇してるの？」「〇〇してる人は損してます」系の否定・対立軸系（約30%）"
        ),
        "hook_style": "「銀行が絶対教えない」「まだ〇〇してるの？」「正直に言います、損してます」「知ってる人だけ得してる」",
    },
    "lifehack": {
        "desc": "ライフハック・効率化",
        "instruction": (
            "スマホ裏技・時短術・仕事効率化・便利グッズ・神アプリなどのテーマを1つ提案してください。"
            "以下の型を意識して、視聴者が「今すぐ試したい」と思うテーマを選んでください。\n"
            "・「これ神」「知らないと人生損」系の裏技Tips（約40%）\n"
            "・「〇〇使ってる人、もったいなすぎる」「え、こんな使い方できるの？」系の驚き系（約30%）\n"
            "・「〇〇はもうやめて」「それ非効率です」系の否定から入る系（約30%）"
        ),
        "hook_style": "「これ知らないのは損」「〇〇はもうやめて」「〇〇使ってる人もったいなすぎる」「やばすぎる裏技」",
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
