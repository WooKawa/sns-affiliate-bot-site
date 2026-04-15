"""
動画素材取得モジュール
Pexels APIから背景動画を取得・ダウンロードする
"""

import os
import requests

PEXELS_API_BASE = "https://api.pexels.com/videos/search"
BACKGROUND_PATH_TEMPLATE = "/tmp/background_{}.mp4"


def _get_api_key() -> str:
    """Pexels APIキーを取得する"""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise ValueError("環境変数 PEXELS_API_KEY が設定されていません")
    return api_key


def _search_videos(keyword: str, api_key: str, per_page: int = 10) -> list:
    """Pexels APIで動画を検索する"""
    headers = {"Authorization": api_key}
    params = {
        "query": keyword,
        "per_page": per_page,
        "orientation": "portrait",  # 縦型優先
    }

    response = requests.get(PEXELS_API_BASE, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    videos = data.get("videos", [])

    # 縦型動画が見つからない場合はlandscapeで再検索
    if not videos:
        print(f"[video_fetcher] 縦型動画が見つかりません。横型で再検索: '{keyword}'")
        params["orientation"] = "landscape"
        response = requests.get(PEXELS_API_BASE, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        videos = data.get("videos", [])

    return videos


def _select_best_video_file(video: dict) -> dict | None:
    """
    動画から最適な解像度のファイルを選択する
    縦型（height > width）を優先し、なければ横型を返す
    """
    video_files = video.get("video_files", [])
    if not video_files:
        return None

    # 縦型ファイルを優先
    portrait_files = [f for f in video_files if f.get("height", 0) > f.get("width", 0)]
    if portrait_files:
        # 最も高解像度の縦型を選択
        portrait_files.sort(key=lambda f: f.get("height", 0), reverse=True)
        return portrait_files[0]

    # 縦型がなければ横型で最高解像度を選択
    video_files.sort(key=lambda f: f.get("height", 0), reverse=True)
    return video_files[0]


def _download_video(url: str, output_path: str, max_retries: int = 3) -> str:
    """動画ファイルをダウンロードする（タイムアウト300秒・3回リトライ）"""
    print(f"[video_fetcher] ダウンロード中: {url[:80]}...")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = os.path.getsize(output_path)
            print(f"[video_fetcher] ダウンロード完了: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
            return output_path

        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt < max_retries:
                print(f"[video_fetcher] ダウンロード失敗 ({attempt}/{max_retries}): {e} - リトライします")
            else:
                raise


def fetch_videos(scenes: list, video_type: str) -> list:
    """
    シーンのキーワードごとに動画を取得・ダウンロードする

    Args:
        scenes: シーンのリスト [{"keyword": str, "duration": int, "text": str}, ...]
        video_type: "short" または "long"

    Returns:
        ダウンロードしたファイルパスのリスト
    """
    print(f"[video_fetcher] 動画取得開始: {len(scenes)}シーン, type={video_type}")

    api_key = _get_api_key()
    max_clips = 2 if video_type == "short" else 8

    downloaded_paths = []
    scenes_to_fetch = scenes[:max_clips]

    for i, scene in enumerate(scenes_to_fetch):
        keyword = scene.get("keyword", "japan")
        output_path = BACKGROUND_PATH_TEMPLATE.format(i)

        print(f"[video_fetcher] シーン{i + 1}/{len(scenes_to_fetch)}: キーワード='{keyword}'")

        try:
            videos = _search_videos(keyword, api_key)

            if not videos:
                # フォールバック: 汎用キーワードで再試行
                print(f"[video_fetcher] '{keyword}' で動画が見つかりません。'Japan city' で再試行します")
                videos = _search_videos("Japan city", api_key)

            if not videos:
                raise ValueError(f"動画が見つかりませんでした: keyword='{keyword}'")

            # 最初の動画を使用
            video = videos[0]
            video_file = _select_best_video_file(video)

            if not video_file:
                raise ValueError(f"適切な動画ファイルが見つかりませんでした: keyword='{keyword}'")

            download_url = video_file.get("link")
            if not download_url:
                raise ValueError(f"ダウンロードURLが取得できませんでした: keyword='{keyword}'")

            _download_video(download_url, output_path)
            downloaded_paths.append(output_path)

        except Exception as e:
            print(f"[video_fetcher] エラー (シーン{i + 1}): {e}")
            # エラーが発生しても続行（後でデフォルト動画を使用することも検討）
            if downloaded_paths:
                # 前のクリップを再利用
                print(f"[video_fetcher] シーン{i + 1}: 前のクリップを再利用します")
                downloaded_paths.append(downloaded_paths[-1])
            else:
                raise

    print(f"[video_fetcher] 動画取得完了: {len(downloaded_paths)}ファイル")
    return downloaded_paths


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="動画取得テスト")
    parser.add_argument("--keyword", required=True, help="検索キーワード")
    parser.add_argument("--type", choices=["short", "long"], default="short")
    args = parser.parse_args()

    test_scenes = [{"keyword": args.keyword, "duration": 30, "text": "テスト"}]
    paths = fetch_videos(test_scenes, args.type)
    print(f"取得完了: {paths}")
