"""
instagram_uploader.py - Meta Graph API で Instagram Reels を投稿するモジュール

投稿フロー:
  1. /tmp/output.mp4 を Google Cloud Storage に一時アップロード（公開URL取得）
  2. Meta Graph API でReelsコンテナを作成
  3. コンテナのステータスをポーリング（最大10分）
  4. コンテナを公開（POST /media_publish）
  5. GCSから一時ファイルを削除

認証:
  Instagram: ジャンルごとに別アカウントのアクセストークン
  GCS: GOOGLE_SERVICE_ACCOUNT_JSON（既存サービスアカウントを流用）

環境変数:
  INSTAGRAM_ACCESS_TOKEN_ZATUGAN / _SETSUYAKU / _LIFEHACK
  INSTAGRAM_USER_ID_ZATUGAN / _SETSUYAKU / _LIFEHACK
  GCS_BUCKET_NAME
  GOOGLE_SERVICE_ACCOUNT_JSON
"""

import os
import time
import json
import uuid
import logging
import requests
from google.oauth2.service_account import Credentials
from google.cloud import storage

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
VIDEO_PATH = "/tmp/output.mp4"
MAX_RETRIES = 3
POLL_INTERVAL = 30   # 秒
POLL_MAX = 20        # 最大ポーリング回数（= 10分）

GENRE_TO_ENV = {
    "zatugan": ("INSTAGRAM_ACCESS_TOKEN_ZATUGAN", "INSTAGRAM_USER_ID_ZATUGAN"),
    "setsuyaku": ("INSTAGRAM_ACCESS_TOKEN_SETSUYAKU", "INSTAGRAM_USER_ID_SETSUYAKU"),
    "lifehack": ("INSTAGRAM_ACCESS_TOKEN_LIFEHACK", "INSTAGRAM_USER_ID_LIFEHACK"),
}

GCS_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def upload_video(
    genre: str,
    description: str,
    video_path: str = VIDEO_PATH,
) -> str:
    """
    Instagram Reels として動画を投稿する。

    Args:
        genre: 'zatugan' | 'setsuyaku' | 'lifehack'
        description: キャプション（ハッシュタグ含む）
        video_path: アップロードする動画ファイルパス

    Returns:
        Instagram投稿ID
    """
    token_env, user_id_env = GENRE_TO_ENV.get(genre, (None, None))
    if not token_env:
        raise ValueError(f"Unknown genre: '{genre}'")

    access_token = os.environ.get(token_env)
    user_id = os.environ.get(user_id_env)
    if not access_token:
        raise EnvironmentError(f"'{token_env}' is not set")
    if not user_id:
        raise EnvironmentError(f"'{user_id_env}' is not set")

    # Step 1: GCSに動画を一時アップロード → 公開URL取得
    gcs_blob_name = f"tmp_reels/{uuid.uuid4()}.mp4"
    video_url = _upload_to_gcs(video_path, gcs_blob_name)
    logger.info(f"GCS temporary URL: {video_url}")

    try:
        # Step 2: Reelsコンテナを作成
        container_id = _create_reels_container(user_id, access_token, video_url, description)
        logger.info(f"Reels container created: {container_id}")

        # Step 3: コンテナステータスをポーリング
        _wait_for_container(user_id, access_token, container_id)

        # Step 4: 公開
        post_id = _publish_container(user_id, access_token, container_id)
        logger.info(f"Instagram Reels published: post_id={post_id}")
        return post_id

    finally:
        # Step 5: GCS一時ファイルを削除
        _delete_gcs_blob(gcs_blob_name)


# ──────────────────────────────────────────────
# GCS操作
# ──────────────────────────────────────────────

def _get_gcs_client():
    """サービスアカウントJSONからGCSクライアントを生成する"""
    service_account_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds_dict = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=GCS_SCOPES)
    return storage.Client(credentials=creds, project=creds_dict.get("project_id"))


def _upload_to_gcs(video_path: str, blob_name: str) -> str:
    """
    動画ファイルをGCSにアップロードして公開URLを返す。
    アップロード後にオブジェクトを一時公開（IAM公開設定済みバケットを前提）。
    """
    bucket_name = os.environ["GCS_BUCKET_NAME"]
    client = _get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    blob.upload_from_filename(video_path, content_type="video/mp4")
    blob.make_public()

    public_url = blob.public_url
    logger.info(f"Uploaded to GCS: {public_url}")
    return public_url


def _delete_gcs_blob(blob_name: str):
    """GCS一時ファイルを削除する（エラーは無視）"""
    try:
        bucket_name = os.environ["GCS_BUCKET_NAME"]
        client = _get_gcs_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()
        logger.info(f"GCS blob deleted: {blob_name}")
    except Exception as e:
        logger.warning(f"GCS blob deletion failed (non-fatal): {e}")


# ──────────────────────────────────────────────
# Meta Graph API操作
# ──────────────────────────────────────────────

def _create_reels_container(
    user_id: str, access_token: str, video_url: str, caption: str
) -> str:
    """Reelsコンテナを作成してコンテナIDを返す"""
    url = f"{GRAPH_API_BASE}/{user_id}/media"
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": access_token,
    }

    for attempt in range(MAX_RETRIES):
        resp = requests.post(url, params=params, timeout=60)
        try:
            resp.raise_for_status()
            data = resp.json()
            if "id" in data:
                return data["id"]
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt * 5
                logger.warning(f"Container creation failed (attempt {attempt + 1}): {e}. Retry in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed to create Reels container: {resp.text}")

    raise RuntimeError("Failed to create Reels container after retries")


def _wait_for_container(user_id: str, access_token: str, container_id: str):
    """コンテナが FINISHED になるまでポーリングで待機する"""
    url = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code",
        "access_token": access_token,
    }

    for i in range(POLL_MAX):
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status_code", "")
        logger.info(f"Container status ({i + 1}/{POLL_MAX}): {status}")

        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Reels container processing failed: {data}")

        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Container {container_id} did not finish within {POLL_MAX * POLL_INTERVAL}s")


def _publish_container(user_id: str, access_token: str, container_id: str) -> str:
    """コンテナを公開して投稿IDを返す"""
    url = f"{GRAPH_API_BASE}/{user_id}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    resp = requests.post(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if "id" not in data:
        raise RuntimeError(f"Publish failed: {data}")

    return data["id"]
