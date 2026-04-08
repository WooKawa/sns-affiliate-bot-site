# sns-affiliate-bot

TikTok × Instagram Reels × YouTube Shorts 3媒体自動投稿 + アフィリエイト収益化システム

## システム概要

| 項目 | 内容 |
|------|------|
| ジャンル | zatugan（雑学）/ setsuyaku（節約）/ lifehack（ライフハック） |
| 投稿先 | TikTok・Instagram Reels・YouTube Shorts（3媒体同時） |
| 動画フォーマット | Short のみ（40秒・縦型 1080×1920） |
| 収益化 | アフィリエイトのみ（案件マスターシート + Gemini自動選定） |
| 自動改善 | 週次ループ（analytics → 分析 → プロンプト更新 → レポート） |
| 月額コスト | ¥0（GitHub Public・全ツール無料枠内） |

## ファイル構成

```
sns-affiliate-bot/
├── .github/workflows/
│   ├── generate_short.yml        # 毎日自動投稿（3ジャンル並列）
│   ├── trend_analysis.yml        # 週次トレンド分析
│   └── auto_improve.yml          # 週次自動改善ループ
├── src/
│   ├── spreadsheet.py            # スプレッドシート読み書き
│   ├── theme_generator.py        # テーマ自動生成（ジャンル別）
│   ├── affiliate_selector.py     # 案件マスターからアフィリ自動選定
│   ├── script_generator.py       # 台本・タイトル・説明文生成
│   ├── tts.py                    # 音声合成（既存から流用）
│   ├── video_fetcher.py          # Pexels動画取得（既存から流用）
│   ├── video_composer.py         # 動画合成・字幕焼き込み
│   ├── tiktok_uploader.py        # TikTok Content Posting API v2
│   ├── instagram_uploader.py     # Meta Graph API（Reels）
│   ├── youtube_uploader.py       # YouTube Data API v3
│   ├── trend_analyzer.py         # TikTok Research API トレンド分析
│   ├── analytics_collector.py    # パフォーマンスデータ収集
│   ├── performance_analyzer.py   # Gemini分析
│   ├── prompt_optimizer.py       # プロンプト自動改善
│   ├── weekly_reporter.py        # 週次レポート生成
│   └── main.py                   # メイン実行スクリプト
└── requirements.txt
```

## スプレッドシート設計

各ジャンルで1枚のスプレッドシートを使用（計3枚）。

### メインシート（A〜L列）
| 列 | 内容 |
|----|------|
| A | テーマ |
| B | ジャンル |
| C | ステータス（未処理/処理中/完了/エラー） |
| D | 台本 |
| E | タイトル |
| F | 説明文 |
| G | キーワード(JSON) |
| H | アフィリURL |
| I | 紹介商品名 |
| J | TikTok動画ID |
| K | Instagram投稿ID |
| L | YouTube動画ID |

### 案件マスターシート
| 列 | 内容 |
|----|------|
| A | ジャンル |
| B | カテゴリ |
| C | 商品名 |
| D | ASP |
| E | トラッキングURL |
| F | 想定単価 |
| G | マッチキーワード |
| H | 掲載可能媒体 |
| I | 審査状況 |

## GitHub Secrets（全21個）

```
GOOGLE_SERVICE_ACCOUNT_JSON
GEMINI_API_KEY
PEXELS_API_KEY
GCS_BUCKET_NAME                          # Instagram動画一時ホスティング用
TIKTOK_CLIENT_KEY
TIKTOK_CLIENT_SECRET
TIKTOK_ACCESS_TOKEN_ZATUGAN
TIKTOK_ACCESS_TOKEN_SETSUYAKU
TIKTOK_ACCESS_TOKEN_LIFEHACK
INSTAGRAM_ACCESS_TOKEN_ZATUGAN
INSTAGRAM_ACCESS_TOKEN_SETSUYAKU
INSTAGRAM_ACCESS_TOKEN_LIFEHACK
INSTAGRAM_USER_ID_ZATUGAN
INSTAGRAM_USER_ID_SETSUYAKU
INSTAGRAM_USER_ID_LIFEHACK
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN_ZATUGAN
YOUTUBE_REFRESH_TOKEN_SETSUYAKU
YOUTUBE_REFRESH_TOKEN_LIFEHACK
SPREADSHEET_ID_ZATUGAN
SPREADSHEET_ID_SETSUYAKU
SPREADSHEET_ID_LIFEHACK
```

## 初回セットアップ

1. PHASE 1（あなたの作業）を完了させる
2. GitHub Secrets を上記リストに従って登録
3. 案件マスターシートに承認済み案件を5件以上登録
4. Actions → generate_short → Run workflow → genre: zatugan でテスト
5. J・K・L列に動画IDが入れば成功

## 自動改善ループ（毎週月曜）

```
UTC 7:00  → trend_analysis（トレンド収集・3ジャンル）
UTC 7:30  → auto_improve（analytics → 分析 → プロンプト更新 → レポート）
```

## 注意事項

- TikTok Content Posting APIは申請〜承認に1〜2週間かかる
- Instagram Reels投稿には動画の一時公開URLが必要（GCS使用）
- GCSバケットは同じサービスアカウントで操作可能
- TikTok アナリティクスは暫定スキップ（手動確認が必要）
