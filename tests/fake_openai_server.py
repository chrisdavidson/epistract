"""Stdlib stub of an OpenAI-compatible local model server (llama.cpp-shaped).

Serves ``/v1/models``, ``/props``, ``/health`` and a scriptable
``/v1/chat/completions`` on an ephemeral 127.0.0.1 port so tests never touch a
real model server. No third-party packages.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_DEFAULT_CONTENT = '{"verdict": "supported", "score": 0.9, "reason": "stub"}'


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    # -- helpers ---------------------------------------------------------
    @property
    def stub(self) -> "FakeOpenAIServer":
        return self.server.stub  # type: ignore[attr-defined]

    def _record(self, body: dict | None) -> None:
        self.stub.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "json": body,
            }
        )

    def _send_json(self, status: int, payload, headers: dict | None = None) -> None:
        raw = (
            payload.encode()
            if isinstance(payload, str)
            else json.dumps(payload).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return None

    # -- verbs -----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        self._record(None)
        s = self.stub
        path = self.path.split("?")[0]
        if path == "/v1/models":
            if s.models_status != 200:
                self._send_json(s.models_status, {"error": "models unavailable"})
                return
            data = []
            for mid in s.models:
                entry: dict = {"id": mid, "object": "model", "owned_by": "llamacpp"}
                meta: dict = {}
                if s.n_ctx is not None:
                    meta["n_ctx"] = s.n_ctx
                if meta:
                    entry["meta"] = meta
                if s.max_model_len is not None:
                    entry["max_model_len"] = s.max_model_len
                data.append(entry)
            self._send_json(
                200,
                {
                    "models": [
                        {"name": m, "model": m, "capabilities": ["completion"]}
                        for m in s.models
                    ],
                    "data": data,
                },
            )
        elif path == "/props":
            if s.props_n_ctx is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(
                    200, {"default_generation_settings": {"n_ctx": s.props_n_ctx}}
                )
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path.startswith("/api/v0/models/"):
            if s.lmstudio_ctx is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(200, {"loaded_context_length": s.lmstudio_ctx})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        body = self._read_body()
        self._record(body)
        s = self.stub
        path = self.path.split("?")[0]
        if path == "/api/show":
            if s.ollama_parameters is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(200, {"parameters": s.ollama_parameters})
            return
        if path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return
        item = s.script.popleft() if s.script else None
        if item is None:
            item = ("content", s.default_content, "stop")
        kind = item[0]
        if kind == "drop":
            self.close_connection = True
            self.connection.close()
            return
        if kind == "status":
            _, status, payload, headers = item
            self._send_json(status, payload, headers)
            return
        if kind == "sse":
            deltas = item[1]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for d in deltas:
                chunk = {"choices": [{"index": 0, "delta": {"content": d}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            usage = {
                "choices": [],
                "usage": {"prompt_tokens": 5, "completion_tokens": len(deltas)},
            }
            self.wfile.write(f"data: {json.dumps(usage)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
            return
        _, text, finish = item
        self._send_json(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "model": (body or {}).get("model", "stub"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": finish,
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 7,
                    "total_tokens": 12,
                },
            },
        )


class FakeOpenAIServer:
    """Threaded stub; ``base_url`` is the root (no ``/v1``)."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.script: deque = deque()
        self.models: list[str] = ["Phi-3-mini-4k-instruct-q4.gguf"]
        self.n_ctx: int | None = 4096
        self.props_n_ctx: int | None = 4096
        self.max_model_len: int | None = None
        self.lmstudio_ctx: int | None = None
        self.ollama_parameters: str | None = None
        self.models_status: int = 200
        self.default_content: str = _DEFAULT_CONTENT
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def start(self) -> "FakeOpenAIServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.stub = self  # type: ignore[attr-defined]
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "FakeOpenAIServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- scripting -------------------------------------------------------
    def queue_content(self, text: str, finish_reason: str = "stop") -> None:
        self.script.append(("content", text, finish_reason))

    def queue_status(
        self, status: int, body: dict | str, headers: dict | None = None
    ) -> None:
        self.script.append(("status", status, body, headers or {}))

    def queue_sse(self, deltas: list[str]) -> None:
        self.script.append(("sse", list(deltas)))

    def queue_drop(self) -> None:
        self.script.append(("drop",))

    def queue_429_daily(self) -> None:
        reset_ms = str(int((time.time() + 6 * 3600) * 1000))
        self.queue_status(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Rate limit exceeded: free-models-per-day",
                    "metadata": {"error_type": "rate_limit_exceeded"},
                }
            },
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset_ms},
        )

    def queue_429_transient(self) -> None:
        self.queue_status(
            429,
            {"error": {"code": 429, "message": "Too many requests, slow down"}},
            {"Retry-After": "1", "X-RateLimit-Remaining": "5"},
        )

    def queue_400_rerank(self) -> None:
        self.queue_status(
            400,
            {
                "error": {
                    "code": 400,
                    "message": (
                        "nvidia/nemotron-3.5-rerank-8b:free is a rerank model and "
                        "cannot be used with the chat/completions endpoint"
                    ),
                }
            },
        )
