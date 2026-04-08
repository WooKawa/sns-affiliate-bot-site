"""
affiliate_selector.py - 案件マスターシートからアフィリエイト案件を自動選定するモジュール

1. Geminiでテーマからマッチキーワード（3〜5個）を抽出
2. 案件マスターシートをキーワード検索
3. 候補が複数ある場合はGeminiが最適な1件を選定
4. 選定結果をスプレッドシートのH列（アフィリURL）・I列（商品名）に書き込む

使用モデル: Gemini 2.5 Flash
環境変数: GEMINI_API_KEY
"""

import os
import json
import logging
import argparse
from google import genai
from spreadsheet import SpreadsheetManager

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"


def select_affiliate(genre: str, theme: str, row_index: int) -> dict:
    """
    テーマに最適なアフィリエイト案件を選定してスプレッドシートに記録する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
        theme: 動画テーマ（例: 「朝5分で節約できる習慣」）
        row_index: スプレッドシートの行番号

    Returns:
        {"url": str, "product_name": str, "category": str}
        案件が見つからない場合は {"url": "", "product_name": "", "category": ""}
    """
    sheet = SpreadsheetManager(genre)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Step 1: Geminiでテーマからマッチキーワードを抽出
    keywords = _extract_keywords(client, theme)
    logger.info(f"Extracted keywords: {keywords}")

    # Step 2: 案件マスターシートを検索
    candidates = sheet.get_affiliate_candidates(keywords)
    logger.info(f"Candidates found: {len(candidates)}")

    if not candidates:
        logger.warning("No affiliate candidates found. Using empty values.")
        sheet.update_affiliate_info(row_index, "", "")
        return {"url": "", "product_name": "", "category": ""}

    # Step 3: 候補が1件のみの場合はそのまま採用
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        # Geminiで最適な1件を選定
        chosen = _select_best_candidate(client, theme, candidates)

    url = chosen.get("tracking_url", "")
    product_name = chosen.get("product_name", "")
    category = chosen.get("category", "")

    # Step 4: スプレッドシートに書き込む
    sheet.update_affiliate_info(row_index, url, product_name)
    logger.info(f"Selected: '{product_name}' ({url})")

    return {"url": url, "product_name": product_name, "category": category}


def _extract_keywords(client, theme: str) -> list[str]:
    """Geminiでテーマから検索キーワードを3〜5個抽出する"""
    prompt = f"""動画テーマ「{theme}」に関連するアフィリエイト案件を検索するための
キーワードを3〜5個抽出してください。

条件:
- アフィリエイト案件のマッチングに使う検索キーワードとして適切なもの
- 具体的な商品カテゴリや用途を示すもの
- JSON配列形式のみで返す（例: ["節約", "クレジットカード", "ポイント"]）
- JSONの外にテキストを書かないこと"""

    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw = response.text.strip()

    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    try:
        keywords = json.loads(raw)
        if isinstance(keywords, list):
            return [str(k) for k in keywords[:5]]
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse keywords JSON: {raw}")

    # フォールバック: テーマをそのままキーワードとして使う
    return [theme]


def _select_best_candidate(client, theme: str, candidates: list[dict]) -> dict:
    """Geminiで候補の中から最適な1件を選定する"""
    candidates_text = "\n".join(
        f"{i + 1}. 商品名: {c['product_name']} / カテゴリ: {c['category']} / "
        f"想定単価: {c['unit_price']} / キーワード: {', '.join(c['match_keywords'])}"
        for i, c in enumerate(candidates)
    )

    prompt = f"""動画テーマ「{theme}」に最も適したアフィリエイト案件を選んでください。

【候補一覧】
{candidates_text}

選定基準:
1. テーマとの関連性が高いこと（最重要）
2. 視聴者が購入したいと思える自然な流れであること
3. 想定単価が高いこと

最も適した候補の番号（1〜{len(candidates)}の整数のみ）を返してください。"""

    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw = response.text.strip()

    try:
        idx = int(raw) - 1
        if 0 <= idx < len(candidates):
            logger.info(f"Gemini selected candidate #{idx + 1}: '{candidates[idx]['product_name']}'")
            return candidates[idx]
    except (ValueError, IndexError):
        logger.warning(f"Failed to parse selection: '{raw}'. Using first candidate.")

    return candidates[0]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="アフィリエイト案件自動選定")
    parser.add_argument("--genre", required=True, choices=["zatugan", "setsuyaku", "lifehack"])
    parser.add_argument("--theme", required=True, help="動画テーマ")
    parser.add_argument("--row", required=True, type=int, help="スプレッドシートの行番号")
    args = parser.parse_args()

    result = select_affiliate(args.genre, args.theme, args.row)
    print(json.dumps(result, ensure_ascii=False, indent=2))
