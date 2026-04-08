"""
spreadsheet.py - Googleスプレッドシート読み書きモジュール（3ジャンル対応版）

ジャンルごとに別スプレッドシートを参照する。
環境変数:
  SPREADSHEET_ID_ZATUGAN    雑学ジャンル用スプレッドシートID
  SPREADSHEET_ID_SETSUYAKU  節約ジャンル用スプレッドシートID
  SPREADSHEET_ID_LIFEHACK   ライフハックジャンル用スプレッドシートID

メインシート列構成（A〜L列）:
  A: テーマ          B: ジャンル        C: ステータス
  D: 台本            E: タイトル        F: 説明文
  G: キーワード(JSON) H: アフィリURL     I: 紹介商品名
  J: TikTok動画ID   K: Instagram投稿ID  L: YouTube動画ID

案件マスターシート列構成:
  A: ジャンル  B: カテゴリ  C: 商品名  D: ASP  E: トラッキングURL
  F: 想定単価  G: マッチキーワード  H: 掲載可能媒体  I: 審査状況
"""

import os
import json
import logging
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GENRE_TO_ENV = {
    "zatugan": "SPREADSHEET_ID_ZATUGAN",
    "setsuyaku": "SPREADSHEET_ID_SETSUYAKU",
    "lifehack": "SPREADSHEET_ID_LIFEHACK",
}

# メインシート列番号
COL_THEME = 1
COL_GENRE = 2
COL_STATUS = 3
COL_SCRIPT = 4
COL_TITLE = 5
COL_DESCRIPTION = 6
COL_KEYWORDS = 7
COL_AFFILI_URL = 8
COL_PRODUCT_NAME = 9
COL_TIKTOK_ID = 10
COL_INSTAGRAM_ID = 11
COL_YOUTUBE_ID = 12

STATUS_PENDING = "未処理"
STATUS_PROCESSING = "処理中"
STATUS_DONE = "完了"
STATUS_ERROR = "エラー"

VALID_GENRES = ("zatugan", "setsuyaku", "lifehack")


class SpreadsheetManager:
    def __init__(self, genre: str):
        if genre not in VALID_GENRES:
            raise ValueError(f"Invalid genre: '{genre}'. Must be one of {VALID_GENRES}")

        self.genre = genre

        service_account_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        creds_dict = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        self.client = gspread.authorize(creds)

        env_key = GENRE_TO_ENV[genre]
        self.sheet_id = os.environ[env_key]
        self.spreadsheet = self.client.open_by_key(self.sheet_id)
        self.main_sheet = self.spreadsheet.sheet1
        logger.info(f"SpreadsheetManager initialized: genre={genre}, sheet_id={self.sheet_id}")

    # ──────────────────────────────────────────────
    # メインシート操作
    # ──────────────────────────────────────────────

    def get_all_themes(self) -> list[str]:
        """メインシートのテーマ列（A列）を全て返す"""
        values = self.main_sheet.col_values(COL_THEME)
        return [v.strip() for v in values[1:] if v.strip()]

    def add_new_row(self, theme: str) -> int:
        """新しい行を追記してrow_indexを返す"""
        new_row = [
            theme, self.genre, STATUS_PENDING,
            "", "", "", "", "", "",
            "", "", "",
        ]
        self.main_sheet.append_row(new_row, value_input_option="RAW")
        all_values = self.main_sheet.get_all_values()
        row_index = len(all_values)
        logger.info(f"Added new row at index {row_index}: theme='{theme}'")
        return row_index

    def get_pending_row(self) -> tuple[int, str] | None:
        """
        ステータスが「未処理」の最初の行を返す。
        Returns:
            (row_index, theme) または None
        """
        all_rows = self.main_sheet.get_all_values()
        for i, row in enumerate(all_rows[1:], start=2):
            status = row[COL_STATUS - 1] if len(row) >= COL_STATUS else ""
            theme = row[COL_THEME - 1] if len(row) >= COL_THEME else ""
            if status == STATUS_PENDING and theme:
                logger.info(f"Pending row found: index={i}, theme='{theme}'")
                return i, theme
        logger.warning("No pending row found")
        return None

    def update_status(self, row_index: int, status: str, error_msg: str = ""):
        """ステータスを更新する。エラー時はエラー内容をD列に記録"""
        self.main_sheet.update_cell(row_index, COL_STATUS, status)
        if error_msg and status == STATUS_ERROR:
            self.main_sheet.update_cell(row_index, COL_SCRIPT, f"[ERROR] {error_msg}")
        logger.info(f"Row {row_index}: status -> '{status}'")

    def update_script_data(self, row_index: int, script_data: dict):
        """台本・タイトル・説明文・シーン情報を書き込む"""
        self.main_sheet.update_cell(row_index, COL_SCRIPT, script_data.get("script", ""))
        self.main_sheet.update_cell(row_index, COL_TITLE, script_data.get("title", ""))
        self.main_sheet.update_cell(row_index, COL_DESCRIPTION, script_data.get("description", ""))
        keywords_json = json.dumps(script_data.get("scenes", []), ensure_ascii=False)
        self.main_sheet.update_cell(row_index, COL_KEYWORDS, keywords_json)
        logger.info(f"Row {row_index}: script data updated")

    def update_affiliate_info(self, row_index: int, url: str, product_name: str):
        """アフィリURL・商品名をH列・I列に書き込む"""
        self.main_sheet.update_cell(row_index, COL_AFFILI_URL, url)
        self.main_sheet.update_cell(row_index, COL_PRODUCT_NAME, product_name)
        logger.info(f"Row {row_index}: affiliate url='{url}', product='{product_name}'")

    def update_platform_id(self, row_index: int, platform: str, video_id: str):
        """
        投稿完了後に各プラットフォームの動画IDを記録する。
        platform: 'tiktok' | 'instagram' | 'youtube'
        """
        col_map = {
            "tiktok": COL_TIKTOK_ID,
            "instagram": COL_INSTAGRAM_ID,
            "youtube": COL_YOUTUBE_ID,
        }
        col = col_map.get(platform)
        if col is None:
            raise ValueError(f"Unknown platform: '{platform}'")
        self.main_sheet.update_cell(row_index, col, video_id)
        logger.info(f"Row {row_index}: {platform}_id -> '{video_id}'")

    # ──────────────────────────────────────────────
    # 案件マスターシート操作
    # ──────────────────────────────────────────────

    def _get_sheet(self, name: str, create_if_missing: bool = True):
        """シート名からワークシートを取得。なければ作成する"""
        try:
            return self.spreadsheet.worksheet(name)
        except gspread.exceptions.WorksheetNotFound:
            if not create_if_missing:
                return None
            logger.info(f"Sheet '{name}' not found. Creating...")
            return self.spreadsheet.add_worksheet(title=name, rows=1000, cols=20)

    def get_affiliate_candidates(self, keywords: list[str]) -> list[dict]:
        """
        案件マスターシートからキーワードにマッチする案件を返す。
        審査状況が「承認済み」のもののみ対象。
        """
        sheet = self._get_sheet("案件マスター")
        all_rows = sheet.get_all_values()
        if len(all_rows) < 2:
            return []

        results = []
        for row in all_rows[1:]:
            if len(row) < 9:
                continue
            genre_col = row[0].strip()
            category = row[1].strip()
            product_name = row[2].strip()
            asp = row[3].strip()
            tracking_url = row[4].strip()
            unit_price = row[5].strip()
            match_keywords_str = row[6].strip()
            media = row[7].strip()
            status = row[8].strip()

            if status != "承認済み":
                continue
            if not tracking_url or not product_name:
                continue

            # ジャンルフィルタ（空欄の場合は全ジャンル対象）
            if genre_col and genre_col != self.genre:
                continue

            # キーワードマッチ
            match_keywords = [k.strip() for k in match_keywords_str.split(",") if k.strip()]
            matched = any(
                any(mk in kw or kw in mk for mk in match_keywords)
                for kw in keywords
            )
            if not matched and match_keywords:
                continue

            results.append({
                "genre": genre_col,
                "category": category,
                "product_name": product_name,
                "asp": asp,
                "tracking_url": tracking_url,
                "unit_price": unit_price,
                "match_keywords": match_keywords,
                "media": media,
            })

        logger.info(f"Affiliate candidates found: {len(results)}")
        return results

    # ──────────────────────────────────────────────
    # トレンドシート操作
    # ──────────────────────────────────────────────

    def get_latest_trend(self) -> dict | None:
        """trend_{genre}シートの最新行を辞書で返す"""
        sheet_name = f"trend_{self.genre}"
        sheet = self._get_sheet(sheet_name)
        all_rows = sheet.get_all_values()
        data_rows = [r for r in all_rows if r and r[0] and r[0] != "分析日"]
        if not data_rows:
            logger.warning(f"No trend data in '{sheet_name}'")
            return None

        latest = data_rows[-1]

        def safe_json(val, default):
            try:
                return json.loads(val) if val else default
            except Exception:
                return default

        return {
            "analyzed_at": latest[0] if len(latest) > 0 else "",
            "title_patterns": safe_json(latest[1] if len(latest) > 1 else "", []),
            "hook_style": latest[2] if len(latest) > 2 else "",
            "recommended_hashtags": safe_json(latest[3] if len(latest) > 3 else "", []),
        }

    def append_trend_data(self, data: dict):
        """trend_{genre}シートにトレンドデータを追記する"""
        sheet_name = f"trend_{self.genre}"
        sheet = self._get_sheet(sheet_name)
        row = [
            data.get("analyzed_at", ""),
            json.dumps(data.get("title_patterns", []), ensure_ascii=False),
            data.get("hook_style", ""),
            json.dumps(data.get("recommended_hashtags", []), ensure_ascii=False),
        ]
        sheet.append_row(row, value_input_option="RAW")
        logger.info(f"Trend data appended to '{sheet_name}'")

    # ──────────────────────────────────────────────
    # prompt_hints シート操作（自動改善ループ連携）
    # ──────────────────────────────────────────────

    def get_prompt_hints(self) -> dict | None:
        """prompt_hintsシートの最新行を返す"""
        sheet = self._get_sheet("prompt_hints")
        all_rows = sheet.get_all_values()
        data_rows = [r for r in all_rows if r and r[0] and r[0] != "週"]
        if not data_rows:
            return None
        latest = data_rows[-1]
        return {
            "week": latest[0] if len(latest) > 0 else "",
            "theme_hint": latest[1] if len(latest) > 1 else "",
            "script_hint": latest[2] if len(latest) > 2 else "",
        }

    def append_prompt_hints(self, week: str, theme_hint: str, script_hint: str):
        """prompt_hintsシートに新しいヒントを追記する"""
        sheet = self._get_sheet("prompt_hints")
        sheet.append_row([week, theme_hint, script_hint], value_input_option="RAW")
        logger.info(f"Prompt hints appended for week: {week}")

    # ──────────────────────────────────────────────
    # analytics シート操作
    # ──────────────────────────────────────────────

    def append_analytics(self, data: dict):
        """analyticsシートにパフォーマンスデータを追記する"""
        sheet = self._get_sheet("analytics")
        row = [
            data.get("date", ""),
            data.get("genre", self.genre),
            data.get("platform", ""),
            data.get("video_id", ""),
            data.get("views", 0),
            data.get("completion_rate", 0),
            data.get("cvr", 0),
            data.get("likes", 0),
            data.get("comments", 0),
            data.get("shares", 0),
        ]
        sheet.append_row(row, value_input_option="RAW")

    def get_analytics_recent(self, weeks: int = 4) -> list[dict]:
        """analyticsシートから直近N週分のデータを返す"""
        from datetime import datetime, timedelta
        sheet = self._get_sheet("analytics")
        all_rows = sheet.get_all_values()
        if len(all_rows) < 2:
            return []

        cutoff = datetime.now() - timedelta(weeks=weeks)
        results = []
        for row in all_rows[1:]:
            if len(row) < 4:
                continue
            try:
                date_str = row[0]
                row_date = datetime.strptime(date_str, "%Y-%m-%d")
                if row_date < cutoff:
                    continue
            except ValueError:
                continue
            results.append({
                "date": row[0],
                "genre": row[1] if len(row) > 1 else "",
                "platform": row[2] if len(row) > 2 else "",
                "video_id": row[3] if len(row) > 3 else "",
                "views": row[4] if len(row) > 4 else 0,
                "completion_rate": row[5] if len(row) > 5 else 0,
                "cvr": row[6] if len(row) > 6 else 0,
                "likes": row[7] if len(row) > 7 else 0,
                "comments": row[8] if len(row) > 8 else 0,
                "shares": row[9] if len(row) > 9 else 0,
            })
        return results

    # ──────────────────────────────────────────────
    # analysis シート操作
    # ──────────────────────────────────────────────

    def append_analysis(self, week: str, analysis: dict):
        """analysisシートにGemini分析結果を追記する"""
        sheet = self._get_sheet("analysis")
        sheet.append_row([
            week,
            json.dumps(analysis.get("top_themes", []), ensure_ascii=False),
            json.dumps(analysis.get("effective_hooks", []), ensure_ascii=False),
            json.dumps(analysis.get("weak_patterns", []), ensure_ascii=False),
            json.dumps(analysis.get("recommended_focus", []), ensure_ascii=False),
        ], value_input_option="RAW")
        logger.info(f"Analysis appended for week: {week}")

    def get_latest_analysis(self) -> dict | None:
        """analysisシートの最新行を返す"""
        sheet = self._get_sheet("analysis", create_if_missing=False)
        if sheet is None:
            return None
        all_rows = sheet.get_all_values()
        data_rows = [r for r in all_rows if r and r[0] and r[0] != "週"]
        if not data_rows:
            return None

        def safe_json(val, default):
            try:
                return json.loads(val) if val else default
            except Exception:
                return default

        latest = data_rows[-1]
        return {
            "week": latest[0] if len(latest) > 0 else "",
            "top_themes": safe_json(latest[1] if len(latest) > 1 else "", []),
            "effective_hooks": safe_json(latest[2] if len(latest) > 2 else "", []),
            "weak_patterns": safe_json(latest[3] if len(latest) > 3 else "", []),
            "recommended_focus": safe_json(latest[4] if len(latest) > 4 else "", []),
        }

    # ──────────────────────────────────────────────
    # weekly_report シート操作
    # ──────────────────────────────────────────────

    def append_weekly_report(self, week: str, report: dict):
        """weekly_reportシートに週次レポートを追記する"""
        sheet = self._get_sheet("weekly_report")
        sheet.append_row([
            week,
            report.get("total_views", 0),
            report.get("total_cv", 0),
            report.get("estimated_revenue", 0),
            json.dumps(report.get("recommended_themes", []), ensure_ascii=False),
            json.dumps(report.get("affili_warnings", []), ensure_ascii=False),
            report.get("error_count", 0),
            report.get("error_summary", ""),
        ], value_input_option="RAW")
        logger.info(f"Weekly report appended for week: {week}")
