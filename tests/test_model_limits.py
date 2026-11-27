"""What is actually sent to the model API, and what happens when it rate-limits us. Local stand-in server only."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import begin
from drill import agents, insights


@pytest.fixture
def server(monkeypatch):
    box = {"status": 200, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            box["requests"].append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            if box["status"] == 429:
                data = b'{"error":{"message":"rate limited","type":"rate_limit_error"}}'
            else:
                data = json.dumps({
                    "id": "resp_1", "object": "response", "created_at": 1, "status": "completed", "model": "s",
                    "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
                    "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                              "input_tokens_details": {"cached_tokens": 0},
                              "output_tokens_details": {"reasoning_tokens": 0}}}).encode()
            self.send_response(box["status"])
            self.send_header("content-type", "application/json")
            self.send_header("retry-after-ms", "10")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENAI_API_KEY", "local-stand-in")
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{httpd.server_port}/v1")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    yield box
    httpd.shutdown()
    httpd.server_close()


def test_T09_replies_are_token_capped_and_not_stored(coord, server):
    d = begin(coord)
    asyncio.run(agents.answer(coord, d, "what is the rollback order?"))
    sent = server["requests"][-1]
    assert sent["max_output_tokens"] == agents.MAX_OUTPUT_TOKENS <= 1000
    assert sent["store"] is False


def test_rate_limit_is_retried_a_bounded_number_of_times_then_fails_safely(coord, server):
    server["status"] = 429
    d = begin(coord)
    with pytest.raises(insights.DrillError) as error:
        asyncio.run(insights.brief(coord, d))
    assert error.value.code == "MODEL_FAILED"
    assert len(server["requests"]) == 3  # first try plus the client library's two retries
    assert coord.view(d)["status"] == "active"
    assert "local-stand-in" not in error.value.message
