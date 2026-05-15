"""One-time YouTube OAuth dance — captures a refresh token for ``.env``.

Run once after creating a Desktop OAuth client in Google Cloud Console:

    uv run python -m tradefarm.tools.youtube_auth

The script:

1. Prompts for the client_id and client_secret from the OAuth client.
2. Opens a tiny localhost HTTP server on a free ephemeral port.
3. Prints an auth URL — open it in your browser, sign in to the YouTube
   account whose live broadcasts you want to read, and grant
   ``youtube.readonly`` access.
4. Google redirects back to ``http://localhost:<port>?code=...`` and the
   server captures the code.
5. The code is exchanged for a refresh token via the OAuth token endpoint.
6. The refresh token is printed for the operator to copy into ``.env``:

       YOUTUBE_CHAT_ENABLED=true
       YOUTUBE_CLIENT_ID=<id>
       YOUTUBE_CLIENT_SECRET=<secret>
       YOUTUBE_REFRESH_TOKEN=<token-printed-here>

This module deliberately avoids importing the rest of the app (config,
storage, etc.) so the script keeps working even when ``.env`` is empty —
it's meant to be the *bootstrapping* tool that produces the credentials in
the first place.
"""
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import httpx


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


@dataclass
class _CapturedCode:
    code: Optional[str] = None
    error: Optional[str] = None


def _free_port() -> int:
    """Bind a temporary socket to find a free port and release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_handler(captured: _CapturedCode, done: threading.Event):
    """Return a ``BaseHTTPRequestHandler`` subclass that stores the
    OAuth code/error on ``captured`` and signals ``done``.
    """

    class _Handler(http.server.BaseHTTPRequestHandler):
        # Silence the default per-request access log.
        def log_message(self, fmt, *args):  # noqa: D401, ARG002
            return

        def do_GET(self):  # noqa: N802 — http.server API
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            error = params.get("error", [None])[0]
            captured.code = code
            captured.error = error
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if code:
                body = (
                    b"<h1>YouTube auth complete.</h1>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                )
            else:
                msg = error or "no code in callback"
                body = (
                    b"<h1>YouTube auth failed.</h1><p>"
                    + msg.encode("utf-8", errors="replace")
                    + b"</p>"
                )
            self.wfile.write(body)
            done.set()

    return _Handler


def _wait_for_code(port: int) -> _CapturedCode:
    """Run a one-shot HTTP server on ``port`` and block until it captures the
    OAuth redirect.
    """
    captured = _CapturedCode()
    done = threading.Event()
    handler_cls = _build_handler(captured, done)
    with socketserver.TCPServer(("127.0.0.1", port), handler_cls) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            done.wait()
        finally:
            httpd.shutdown()
    return captured


def _exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    body = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(TOKEN_URL, data=body)
        if r.status_code != 200:
            raise RuntimeError(
                f"token exchange failed: HTTP {r.status_code} — {r.text[:500]}"
            )
        return r.json()


def main() -> int:
    print("YouTube OAuth setup — one-time refresh-token capture.")
    print()
    print("Prerequisites:")
    print(
        "  1. Enable 'YouTube Data API v3' in your Google Cloud project"
        " (APIs & Services -> Library)."
    )
    print(
        "  2. Create an OAuth 2.0 Client ID of type 'Desktop app'"
        " (APIs & Services -> Credentials)."
    )
    print(
        "  3. Add your Google account as a 'Test user' under the OAuth"
        " consent screen if the app is in Testing mode."
    )
    print()

    client_id = input("OAuth client_id: ").strip()
    if not client_id:
        print("ERROR: client_id is required.")
        return 1
    client_secret = input("OAuth client_secret: ").strip()
    if not client_secret:
        print("ERROR: client_secret is required.")
        return 1

    port = _free_port()
    redirect_uri = f"http://localhost:{port}"

    qs = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "scope": SCOPE,
        }
    )
    auth_url = f"{AUTH_URL}?{qs}"

    print()
    print("Open this URL in your browser, sign in, and grant access:")
    print()
    print(f"  {auth_url}")
    print()
    print(
        f"Waiting for Google to redirect to {redirect_uri} ..."
        " (this terminal will block here)"
    )

    captured = _wait_for_code(port)
    if captured.error or not captured.code:
        print(f"ERROR: OAuth flow returned no code ({captured.error or 'no code'}).")
        return 1

    print("Got authorization code. Exchanging for tokens ...")
    try:
        data = _exchange_code(client_id, client_secret, captured.code, redirect_uri)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print(
            "ERROR: response did not include a refresh_token. Did you grant"
            " consent for the first time? Re-run after revoking the existing"
            " grant at https://myaccount.google.com/permissions"
        )
        print(f"Raw response: {data}")
        return 1

    print()
    print("SUCCESS. Copy these lines into your project-root .env:")
    print()
    print("  YOUTUBE_CHAT_ENABLED=true")
    print(f"  YOUTUBE_CLIENT_ID={client_id}")
    print(f"  YOUTUBE_CLIENT_SECRET={client_secret}")
    print(f"  YOUTUBE_REFRESH_TOKEN={refresh_token}")
    print()
    print("Then restart the backend; the YouTubeChatPoller will pick it up at boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
