#!/usr/bin/env python3
import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class OpenAIMockServer(ThreadingHTTPServer):
    def __init__(self, server_address, initial_state: str):
        super().__init__(server_address, OpenAIMockRequestHandler)
        self.state = initial_state
        self.state_lock = threading.Lock()

    def get_state(self) -> str:
        with self.state_lock:
            return self.state

    def set_state(self, state: str) -> None:
        with self.state_lock:
            self.state = state


class OpenAIMockRequestHandler(BaseHTTPRequestHandler):
    server: OpenAIMockServer

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send_json(404, {"error": {"message": "Unknown mock endpoint"}})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 0:
            self.rfile.read(content_length)

        if self.server.get_state() == "fail":
            self._send_json(
                429,
                {
                    "error": {
                        "message": "Mock OpenAI quota exceeded",
                        "type": "insufficient_quota",
                        "code": "insufficient_quota",
                    }
                },
            )
            return

        self._send_json(
            200,
            {
                "id": "chatcmpl-watchdog-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def log_message(self, message_format: str, *args) -> None:
        logging.info("%s - %s", self.address_string(), message_format % args)

    def _send_json(self, status_code: int, payload: dict) -> None:
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Toggleable OpenAI Chat Completions mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--initial-state", choices=("ok", "fail"), default="fail")
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s", level=logging.INFO)
    server = OpenAIMockServer((args.host, args.port), args.initial_state)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"OpenAI mock listening on http://{args.host}:{args.port}/v1 (state={server.get_state()})")
    print("Commands: ok, fail, status, quit")

    try:
        while True:
            command = input("mock> ").strip().lower()
            if command in {"ok", "fail"}:
                server.set_state(command)
                print(f"Mock state changed to {command}")
            elif command == "status":
                print(f"Mock state: {server.get_state()}")
            elif command in {"quit", "exit", "q"}:
                return
            elif command:
                print("Unknown command. Use: ok, fail, status, quit")
    except (EOFError, KeyboardInterrupt):
        return
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
