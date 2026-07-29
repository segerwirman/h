"""OAuth desktop PKCE melalui browser eksternal + callback loopback.

Modul kecil ini sengaja provider-agnostic agar Fase 7 dapat memakai seam
yang sama. Ia tidak menyimpan token; wrapper provider wajib memakai
``secrets_store``.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse


class LoopbackOAuthError(RuntimeError):
    pass


def generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - kontrak BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        expected = getattr(self.server, "callback_path", "/callback")
        if parsed.path != expected:
            self.send_error(404)
            return
        query = parse_qs(parsed.query)
        result = {
            "code": (query.get("code") or [""])[0],
            "state": (query.get("state") or [""])[0],
            "error": (query.get("error_description")
                      or query.get("error") or [""])[0],
        }
        setattr(self.server, "oauth_result", result)
        expected_state = str(getattr(self.server, "expected_state", ""))
        state_ok = bool(expected_state) and secrets.compare_digest(
            result["state"], expected_state)
        ok = bool(result["code"] and not result["error"] and state_ok)
        body = ("Autentikasi berhasil. Kembali ke Jarvis."
                if ok else "Autentikasi gagal. Kembali ke Jarvis.")
        payload = ("<!doctype html><meta charset='utf-8'><title>Jarvis OAuth"
                   f"</title><p>{body}</p>").encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _bind(ports: tuple[int, ...], callback_path: str) -> HTTPServer:
    last_error: Exception | None = None
    for port in ports:
        try:
            server = HTTPServer(("127.0.0.1", int(port)), _CallbackHandler)
            setattr(server, "callback_path", callback_path)
            setattr(server, "oauth_result", None)
            server.timeout = 0.5
            return server
        except OSError as exc:
            last_error = exc
    raise LoopbackOAuthError(
        "port callback OAuth tidak tersedia") from last_error


def authorize(*, authorize_url: str, client_id: str, scope: str,
              exchange, ports: tuple[int, ...] = (0,),
              callback_path: str = "/callback",
              redirect_host: str = "localhost",
              extra_params: dict[str, str] | None = None,
              timeout_s: int = 300, open_browser: bool = True) -> dict:
    """Jalankan authorization-code PKCE dan return payload token exchange.

    ``exchange`` dipanggil sebagai ``exchange(code, verifier, redirect_uri)``.
    URL/query callback tidak pernah di-log.
    """
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    server = _bind(ports, callback_path)
    setattr(server, "expected_state", state)
    actual_port = int(server.server_address[1])
    redirect_uri = f"http://{redirect_host}:{actual_port}{callback_path}"
    params = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": scope,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": state,
    }
    params.update(extra_params or {})
    url = f"{authorize_url}?{urlencode(params)}"
    if open_browser:
        try:
            if not webbrowser.open(url):
                raise LoopbackOAuthError(
                    "browser tidak dapat dibuka; salin URL dari UI lalu coba lagi")
        except LoopbackOAuthError:
            server.server_close()
            raise
        except Exception as exc:
            server.server_close()
            raise LoopbackOAuthError(
                "browser eksternal gagal dibuka") from exc

    deadline = time.monotonic() + max(1, int(timeout_s))
    try:
        while time.monotonic() < deadline:
            server.handle_request()
            result = getattr(server, "oauth_result", None)
            if result is not None:
                break
        else:
            raise LoopbackOAuthError("login OAuth timeout")
    finally:
        server.server_close()

    if result.get("error"):
        raise LoopbackOAuthError(f"provider menolak login: {result['error'][:160]}")
    if not result.get("code"):
        raise LoopbackOAuthError("callback OAuth tidak membawa code")
    if not secrets.compare_digest(str(result.get("state", "")), state):
        raise LoopbackOAuthError("state OAuth tidak cocok; login dibatalkan")
    return exchange(result["code"], verifier, redirect_uri)
