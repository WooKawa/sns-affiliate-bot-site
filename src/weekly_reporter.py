"""
weekly_reporter.py - 週次レポート生成・記録モジュール

今週のパフォーマンスサマリーを集計し、
スプレッドシートの「weekly_report」シートに記録する。

レポート内容:
  - 総再生数・総CV数・推定収益（ジャンル別）
  - 来週の推奨テーマ Top5（ジャンル別）
  - アフィリリンク差し替え推奨（CVRが低い商品の警告）
  - エラー件数・エラー内容サマリー

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

# 収益推定: 1CVあたりの平均報酬（ジャンル別の目安）
ESTIMATED_REVENUE_PER_CV = {
    "zatugan": 500,    # 書籍・学習系 平均500円
    "setsuyaku": 2000, # 金融・証券系 平均2000円
    "lifehack": 300,   # Amazon物販 平均300円
}


def generate_reports():
    """全ジャンルの週次レポートを生成してspreadsheetに記録する"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    week = _get_week_label()
    logger.info(f"Weekly report generation started: week={week}")

    for genre in GENRES:
        logger.info(f"=== Generating report for genre: {genre} ===")
        try:
            sheet = SpreadsheetManager(genre)
            records = sheet.get_analytics_recent(weeks=1)  # 今週分
            analysis = sheet.get_latest_analysis()
            error_count, error_summary = _get_error_info(sheet)

            report = _build_report(client, genre, records, analysis, error_count, error_summary)
            sheet.append_weekly_report(week, report)
            logger.info(f"[{genre}] Weekly report saved for week: {week}")

            # サマリーをログに出力
            logger.info(
                f"[{genre}] 総再生数:{report['total_views']} "
                f"CV:{report['total_cv']} "
                f"推定収益:¥{report['estimated_revenue']}"
            )

        except Exception as e:
            logger.error(f"[{genre}] Report generation failed: {e}")

    logger.info("Weekly report generation completed")


def _build_report(
    client,
    genre: str,
    records: list[dict],
    analysis: dict | None,
    error_count: int,
    error_summary: str,
) -> dict:
    """レポートデータを組み立てる"""
    # 集計
    total_views = sum(int(r.get("views", 0) or 0) for r in records)
    # CV数 = 再生数 × CVR（率）の合計
    total_cv = sum(
        int(r.get("views", 0) or 0) * float(r.get("cvr", 0) or 0)
        for r in records
    )
    revenue_per_cv = ESTIMATED_REVENUE_PER_CV.get(genre, 500)
    estimated_revenue = total_cv * revenue_per_cv

    # アフィリリンク警告（CVRが極端に低い場合）
    affili_warnings = _check_affili_performance(records)

    # 来週の推奨テーマをGeminiで生成
    recommended_themes = _generate_recommended_themes(client, genre, analysis)

    return {
        "total_views": total_views,
        "total_cv": total_cv,
        "estimated_revenue": estimated_revenue,
        "recommended_themes": recommended_themes,
        "affili_warnings": affili_warnings,
        "error_count": error_count,
        "error_summary": error_summary,
    }


def _check_affili_performance(records: list[dict]) -> list[str]:
    """CVRが著しく低い動画のアフィリリンク差し替えを警告する"""
    warnings = []
    high_view_low_cvr = [
        r for r in records
        if int(r.get("views", 0) or 0) > 1000 and float(r.get("cvr", 0) or 0) < 0.1
    ]
    if high_view_low_cvr:
        video_ids = [r.get("video_id", "unknown") for r in high_view_low_cvr[:3]]
        warnings.append(
            f"再生数1000超だがCVR0.1%未満の動画あり（{', '.join(video_ids)}）"
            "→ アフィリリンクまたは説明文の見直しを推奨"
        )
    return warnings


def _generate_recommended_themes(
    client, genre: str, analysis: dict | None
) -> list[str]:
    """Geminiで来週の推奨テーマを5個生成する"""
    if not analysis:
        return []

    top_themes = analysis.get("top_themes", [])
    recommended_focus = analysis.get("recommended_focus", [])

    prompt = f"""ジャンル「{genre}」のSNSショート動画の来週の推奨テーマを5つ提案してください。

【今週のパフォーマンスが良かったテーマ傾向】
{chr(10).join(f'- {t}' for t in top_themes)}

【来週の推奨フォーカス方向性】
{chr(10).join(f'- {f}' for f in recommended_focus)}

条件:
- 具体的でTikTok・Instagram・YouTubeで再生されやすいテーマ
- 30文字以内
- JSON配列形式のみで返す
- JSONの外にテキストを書かないこと"""

    for attempt in range(3):
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            themes = json.loads(raw)
            if isinstance(themes, list) and themes:
                return [str(t) for t in themes[:5]]
        except json.JSONDecodeError:
            pass

    return []


def _get_error_info(sheet: SpreadsheetManager) -> tuple[int, str]:
    """メインシートのエラー行数とエラーサマリーを取得する"""
    try:
        all_rows = sheet.main_sheet.get_all_values()
        error_rows = [r for r in all_rows[1:] if len(r) >= 3 and r[2] == "エラー"]
        error_count = len(error_rows)

        if error_rows:
            # D列（台本列）にエラー内容が記録されている
            errors = [r[3][:50] if len(r) >= 4 else "不明" for r in error_rows[:3]]
            summary = " / ".join(errors)
        else:
            summary = ""

        return error_count, summary
    except Exception as e:
        logger.warning(f"Failed to get error info: {e}")
        return 0, ""


def _get_week_label() -> str:
    """今週のラベルを返す（例: 2026-W14）"""
    now = datetime.now(JST)
    return f"{now.strftime('%Y')}-W{now.strftime('%V')}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generate_reports()
