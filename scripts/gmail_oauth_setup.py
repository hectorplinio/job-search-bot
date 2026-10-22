"""One-time setup: turns a Google OAuth "Desktop app" client into the
GMAIL_REFRESH_TOKEN jobbot needs for `jobbot check-mail`.

Before running this:
  1. console.cloud.google.com -> enable the "Gmail API" on your project.
  2. OAuth consent screen (Google Auth Platform) -> add yourself as a test
     user. Keep publishing status "Testing" - no verification needed.
  3. Clients -> Create client -> Application type: Desktop app. Put the
     client id + secret in .env as GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET.
  4. Run this script (no arguments needed once those two are in .env):
       python scripts/gmail_oauth_setup.py
  5. A browser opens, you sign in and accept "View your email messages
     (read-only)". This script catches the redirect on localhost, exchanges
     the code for a refresh token, and writes GMAIL_REFRESH_TOKEN straight
     into .env - it is never printed to the terminal.

The scope is gmail.readonly: this token can never send, label or delete
anything, by construction - not a trust promise, a server-side restriction.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/oauth2callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

_received_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's naming convention
        global _received_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _received_code = (params.get("code") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "Listo, ya puedes cerrar esta pestana." if _received_code else "Algo fallo."
        self.wfile.write(f"<html><body><h2>{message}</h2></body></html>".encode())

    def log_message(self, *_args: object) -> None:  # silence http.server's own logging
        pass


def _wait_for_code() -> str:
    server = HTTPServer(("localhost", PORT), _CallbackHandler)
    server.handle_request()  # blocks for exactly one request, then returns
    if _received_code is None:
        raise RuntimeError("No se recibio el codigo de autorizacion.")
    return _received_code


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed, hardcoded Google URL
        return json.load(response)


def main() -> None:
    import os

    load_dotenv(ENV_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", default=os.getenv("GMAIL_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("GMAIL_CLIENT_SECRET"))
    args = parser.parse_args()
    if not args.client_id or not args.client_secret:
        raise SystemExit(
            "Falta GMAIL_CLIENT_ID o GMAIL_CLIENT_SECRET en .env (o pasalos con "
            "--client-id/--client-secret)."
        )

    auth_url = (
        AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": args.client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",  # forces a refresh_token even on a repeat run
            }
        )
    )
    print(f"Abriendo el navegador. Si no se abre solo, visita:\n{auth_url}\n")
    webbrowser.open(auth_url)

    code = _wait_for_code()
    tokens = _exchange_code(code, args.client_id, args.client_secret)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SystemExit(
            "Google no devolvio un refresh_token. Revoca el acceso en "
            "myaccount.google.com/permissions y vuelve a ejecutar este script."
        )

    set_key(str(ENV_PATH), "GMAIL_CLIENT_ID", args.client_id)
    set_key(str(ENV_PATH), "GMAIL_CLIENT_SECRET", args.client_secret)
    set_key(str(ENV_PATH), "GMAIL_REFRESH_TOKEN", refresh_token)
    print(f"\nListo. GMAIL_REFRESH_TOKEN guardado directamente en {ENV_PATH} (no se imprime aqui).")


if __name__ == "__main__":
    main()
