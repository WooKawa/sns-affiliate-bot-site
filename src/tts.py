"""
音声合成モジュール
Google Cloud Text-to-Speech APIを使ってナレーション音声を生成する
"""

import os
import re
import json
import subprocess
from google.cloud import texttospeech
from google.oauth2.service_account import Credentials

NARRATION_PATH = "/tmp/narration.mp3"
LANGUAGE_CODE = "ja-JP"
VOICE_NAME = "ja-JP-Standard-C"


def _get_tts_client():
    """Text-to-Speech クライアントを初期化する"""
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise ValueError("環境変数 GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")

    service_account_info = json.loads(service_account_json)
    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = texttospeech.TextToSpeechClient(credentials=credentials)
    return client


def _split_text(text: str, max_bytes: int = 4500) -> list:
    """
    テキストを最大バイト数以下のチャンクに分割する（日本語対応）
    日本語は1文字3バイトなので、5000バイト上限に対して4500バイトで分割する
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks = []
    current = ""
    for sentence in text.replace("。", "。\n").split("\n"):
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = current + sentence
        if len(candidate.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_bytes]]


def synthesize_speech(text: str) -> str:
    """
    テキストを音声に変換してMP3ファイルとして保存する
    5000バイト超の場合は分割して複数回APIを呼び出し、音声を結合する

    Args:
        text: ナレーションテキスト

    Returns:
        出力ファイルパス (/tmp/narration.mp3)
    """
    # ナレーター表記を除去（例：「ナレーター「〇〇」」→「〇〇」）
    text = re.sub(r'ナレーター[：:「]', '', text)
    text = re.sub(r'ナレーション[：:]', '', text)

    print(f"[tts] 音声合成開始 ({len(text)}文字 / {len(text.encode('utf-8'))}バイト)")

    client = _get_tts_client()

    # 5000バイト上限対策: 4500バイト以下に分割
    chunks = _split_text(text, max_bytes=4500)
    print(f"[tts] チャンク数: {len(chunks)}")

    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE_CODE,
        name=VOICE_NAME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.5,
        pitch=0.0,
    )

    # 各チャンクをTTS変換
    audio_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"[tts] チャンク {i + 1}/{len(chunks)} 送信中...")
        synthesis_input = texttospeech.SynthesisInput(text=chunk)
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        audio_chunks.append(response.audio_content)

    # チャンクが1つの場合はそのまま保存
    if len(audio_chunks) == 1:
        with open(NARRATION_PATH, "wb") as f:
            f.write(audio_chunks[0])
    else:
        # 複数チャンクはffmpegで正確に結合（バイナリ結合だとタイムスタンプがずれる）
        chunk_paths = []
        for i, chunk_bytes in enumerate(audio_chunks):
            chunk_path = f"/tmp/tts_chunk_{i}.mp3"
            with open(chunk_path, "wb") as f:
                f.write(chunk_bytes)
            chunk_paths.append(chunk_path)

        concat_list = "/tmp/tts_concat_list.txt"
        with open(concat_list, "w") as f:
            for p in chunk_paths:
                f.write(f"file '{p}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c:a", "copy", NARRATION_PATH],
            check=True, capture_output=True,
        )
        print(f"[tts] {len(audio_chunks)}チャンクをffmpegで結合完了")

    file_size = os.path.getsize(NARRATION_PATH)
    print(f"[tts] 音声合成完了: {NARRATION_PATH} ({file_size / 1024:.1f} KB)")

    return NARRATION_PATH


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="音声合成テスト")
    parser.add_argument("--text", required=True, help="合成するテキスト")
    args = parser.parse_args()

    output_path = synthesize_speech(args.text)
    print(f"出力ファイル: {output_path}")
