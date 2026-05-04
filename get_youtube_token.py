"""
YouTube OAuth2 リフレッシュトークン取得スクリプト
=================================================
使い方:
  python get_youtube_token.py

手順:
  1. CLIENT_ID と CLIENT_SECRET を入力
  2. ブラウザが自動で開く → Googleアカウントでログイン → 許可
  3. リフレッシュトークンが自動で取得される
  4. GitHub Secrets に設定する
"""

import urllib.parse
import urllib.request
import json
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ===== YouTube Data API v3 のスコープ =====
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
REDIRECT_URI = "http://localhost:8080"
PORT = 8080

# 認証コードを受け取るグローバル変数
auth_code_received = None


class CallbackHandler(BaseHTTPRequestHandler):
    """ローカルサーバーでGoogleからのリダイレクトを受け取る"""

    def do_GET(self):
        global auth_code_received
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code_received = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
                <html><body style='font-family:sans-serif;text-align:center;padding:50px'>
                <h2>&#x2705; Auth complete!</h2>
                <p>Close this tab and return to the terminal.</p>
                </body></html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # ログ出力を抑制


def main():
    global auth_code_received

    print("=" * 60)
    print("  YouTube リフレッシュトークン取得ツール")
    print("=" * 60)
    print()

    client_id = input("CLIENT_ID を貼り付けてください: ").strip()
    client_secret = input("CLIENT_SECRET を貼り付けてください: ").strip()

    # 認証URLを生成
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

    # ローカルサーバーをバックグラウンドで起動
    server = HTTPServer(("localhost", PORT), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    print()
    print("ブラウザが開きます。Googleアカウントでログインして「許可」してください...")
    print()
    webbrowser.open(auth_url)

    print("認証待ち中...")
    server_thread.join(timeout=120)  # 最大2分待機

    if not auth_code_received:
        print("❌ タイムアウト：2分以内に認証が完了しませんでした。")
        return

    print("認証コードを受信しました。トークンを取得中...")

    # トークンを取得
    token_url = "https://oauth2.googleapis.com/token"
    token_data = urllib.parse.urlencode({
        "code": auth_code_received,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=token_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"\nエラーが発生しました: {e.code}")
        print(error_body)
        return

    refresh_token = result.get("refresh_token")
    if refresh_token:
        print()
        print("=" * 60)
        print("  ✅ リフレッシュトークン取得成功！")
        print("=" * 60)
        print()
        print("REFRESH_TOKEN:")
        print(refresh_token)
        print()
        print("【次のステップ】GitHub Secrets に以下を設定してください:")
        print(f"  YOUTUBE_CLIENT_ID             = {client_id}")
        print(f"  YOUTUBE_CLIENT_SECRET         = {client_secret}")
        print(f"  YOUTUBE_REFRESH_TOKEN_ZATUGAN    = {refresh_token}")
        print(f"  YOUTUBE_REFRESH_TOKEN_SETSUYAKU  = {refresh_token}  （同じGoogleアカウントの場合）")
        print(f"  YOUTUBE_REFRESH_TOKEN_LIFEHACK   = {refresh_token}  （同じGoogleアカウントの場合）")
    else:
        print("\n❌ リフレッシュトークンが取得できませんでした。")
        print("レスポンス内容:")
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
