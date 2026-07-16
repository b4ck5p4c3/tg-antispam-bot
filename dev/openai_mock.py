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
        if not self.path.rstrip("/").endswith("/responses"):
            self._send_json(404, {"error": {"message": "Unknown mock endpoint"}})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        request_body = {}
        if content_length > 0:
            request_body = json.loads(self.rfile.read(content_length))

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

        response_text = self._get_response_text(request_body)
        self._send_json(
            200,
            {
                "id": "resp-openai-mock",
                "object": "response",
                "created_at": int(time.time()),
                "model": request_body.get("model", "gpt-5.6-luna"),
                "output": [
                    {
                        "id": "msg-openai-mock",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": response_text,
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
            },
        )

    def _get_response_text(self, request_body: dict) -> str:
        if self.server.get_state() == "invalid":
            return "not valid JSON"

        response_format = request_body.get("text", {}).get("format", {})
        if response_format.get("type") != "json_schema":
            return "pong"

        message_input = json.loads(request_body.get("input", "{}"))
        target_message = message_input.get("target_message", "").lower()
        is_spam = "[mock:spam]" in target_message
        classification = {
            "verdict": "spam" if is_spam else "not_spam",
            "reason": "Mock spam marker detected." if is_spam else "No mock spam marker detected.",
        }
        return json.dumps(classification, ensure_ascii=False)

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
    parser = argparse.ArgumentParser(description="Toggleable OpenAI Responses API mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--initial-state", choices=("ok", "fail", "invalid"), default="fail")
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s", level=logging.INFO)
    server = OpenAIMockServer((args.host, args.port), args.initial_state)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"OpenAI mock listening on http://{args.host}:{args.port}/v1 (state={server.get_state()})")
    print("Commands: ok, fail, invalid, status, quit")

    try:
        while True:
            command = input("mock> ").strip().lower()
            if command in {"ok", "fail", "invalid"}:
                server.set_state(command)
                print(f"Mock state changed to {command}")
            elif command == "status":
                print(f"Mock state: {server.get_state()}")
            elif command in {"quit", "exit", "q"}:
                return
            elif command:
                print("Unknown command. Use: ok, fail, invalid, status, quit")
    except (EOFError, KeyboardInterrupt):
        return
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
