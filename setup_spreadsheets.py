"""
setup_spreadsheets.py - スプレッドシート初期セットアップ

スプレッドシート3枚（zatugan / setsuyaku / lifehack）に
必要な全シートとヘッダー行を自動作成する。

実行方法:
  SPREADSHEET_ID_ZATUGAN=xxx \
  SPREADSHEET_ID_SETSUYAKU=yyy \
  SPREADSHEET_ID_LIFEHACK=zzz \
  GOOGLE_SERVICE_ACCOUNT_JSON="$(cat your-service-account.json)" \
  python setup_spreadsheets.py
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ジャンルとスプレッドシートIDの対応
GENRES = {
    "zatugan":   os.environ.get("SPREADSHEET_ID_ZATUGAN", ""),
    "setsuyaku": os.environ.get("SPREADSHEET_ID_SETSUYAKU", ""),
    "lifehack":  os.environ.get("SPREADSHEET_ID_LIFEHACK", ""),
}

# シート定義: {シート名: [ヘッダー列リスト]}
SHEET_DEFINITIONS = {
    "メイン": [
        "テーマ", "ジャンル", "ステータス", "台本",
        "タイトル", "説明文", "キーワード(JSON)",
        "アフィリURL", "紹介商品名",
        "TikTok動画ID", "Instagram投稿ID", "YouTube動画ID",
    ],
    "案件マスター": [
        "ジャンル", "カテゴリ", "商品名", "ASP",
        "トラッキングURL", "想定単価", "マッチキーワード",
        "掲載可能媒体", "審査状況",
    ],
    "trend_zatugan": [
        "分析日", "タイトルの型", "冒頭掴みパターン",
        "推奨ハッシュタグ1", "推奨ハッシュタグ2", "推奨ハッシュタグ3",
        "推奨ハッシュタグ4", "推奨ハッシュタグ5", "備考",
    ],
    "trend_setsuyaku": [
        "分析日", "タイトルの型", "冒頭掴みパターン",
        "推奨ハッシュタグ1", "推奨ハッシュタグ2", "推奨ハッシュタグ3",
        "推奨ハッシュタグ4", "推奨ハッシュタグ5", "備考",
    ],
    "trend_lifehack": [
        "分析日", "タイトルの型", "冒頭掴みパターン",
        "推奨ハッシュタグ1", "推奨ハッシュタグ2", "推奨ハッシュタグ3",
        "推奨ハッシュタグ4", "推奨ハッシュタグ5", "備考",
    ],
    "analytics": [
        "日付", "ジャンル", "媒体", "動画ID",
        "再生数", "いいね数", "コメント数", "シェア数",
        "完走率(%)", "リーチ数", "プロフアクセス数", "CVR(%)",
    ],
    "analysis": [
        "分析週", "top_themes", "effective_hooks",
        "weak_patterns", "recommended_focus", "raw_json",
    ],
    "prompt_hints": [
        "更新週", "theme_hint", "script_hint",
    ],
    "weekly_report": [
        "対象週", "総再生数", "総CV数", "推定収益(円)",
        "zatugan再生数", "setsuyaku再生数", "lifehack再生数",
        "来週推奨テーマ1", "来週推奨テーマ2", "来週推奨テーマ3",
        "来週推奨テーマ4", "来週推奨テーマ5",
        "アフィリ差替推奨", "エラー件数", "エラーサマリー",
    ],
}


def get_client() -> gspread.Client:
    """サービスアカウントで認証してgspreadクライアントを返す"""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        raise ValueError("環境変数 GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")

    sa_info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return gspread.authorize(creds)


def setup_spreadsheet(client: gspread.Client, genre: str, spreadsheet_id: str) -> None:
    """1枚のスプレッドシートに全シートとヘッダーを作成する"""
    if not spreadsheet_id:
        print(f"  ⚠️  SPREADSHEET_ID_{genre.upper()} が未設定のためスキップ")
        return

    print(f"\n📊 [{genre}] スプレッドシートをセットアップ中...")
    ss = client.open_by_key(spreadsheet_id)

    # 既存シート名を取得
    existing = {ws.title for ws in ss.worksheets()}

    for sheet_name, headers in SHEET_DEFINITIONS.items():
        if sheet_name in existing:
            print(f"  ✅ 「{sheet_name}」: 既に存在（スキップ）")
            continue

        # 新規シートを作成
        ws = ss.add_worksheet(title=sheet_name, rows=1000, cols=len(headers) + 2)

        # ヘッダー行を書き込み（A1から）
        ws.update([headers], "A1")

        # ヘッダー行を太字・背景色で装飾
        ws.format("A1:Z1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.5},
        })

        print(f"  ✅ 「{sheet_name}」: 作成完了（{len(headers)}列）")

    # デフォルトの「Sheet1」が残っていたら削除
    for ws in ss.worksheets():
        if ws.title in ("Sheet1", "シート1") and len(ss.worksheets()) > 1:
            ss.del_worksheet(ws)
            print(f"  🗑️  デフォルトシートを削除しました")
            break

    print(f"  🎉 [{genre}] セットアップ完了！")
    print(f"      URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")


def main():
    # 環境変数チェック
    missing = [k for k, v in GENRES.items() if not v]
    if missing:
        print(f"⚠️  以下のスプレッドシートIDが未設定です: {missing}")
        print("   設定されているIDのみセットアップします\n")

    print("🔐 Googleサービスアカウントで認証中...")
    client = get_client()
    print("✅ 認証成功\n")

    for genre, spreadsheet_id in GENRES.items():
        setup_spreadsheet(client, genre, spreadsheet_id)

    print("\n" + "=" * 50)
    print("✅ 全スプレッドシートのセットアップが完了しました！")
    print("=" * 50)
    print("\n次のステップ：")
    print("1. 案件マスターシートにアフィリ案件を5件以上登録")
    print("2. GitHubリポジトリにpush")
    print("3. GitHub Secretsに各IDを登録")
    print("   SPREADSHEET_ID_ZATUGAN / _SETSUYAKU / _LIFEHACK")


if __name__ == "__main__":
    main()
