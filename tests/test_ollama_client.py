"""Unit tests for OllamaClient's retry/backoff behaviour, mocking requests.post
directly so the real retry loop is exercised (not simulated)."""
from unittest.mock import MagicMock, patch

from nexus_formatter.ollama_client import OllamaClient, OllamaError, OllamaTruncatedError


def _resp(status_code=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = text
    return r


@patch("nexus_formatter.ollama_client.time.sleep", lambda *_: None)
@patch("nexus_formatter.ollama_client.requests.post")
def test_retries_on_server_error_then_succeeds(mock_post):
    mock_post.side_effect = [
        _resp(500, text="boom"),
        _resp(500, text="boom again"),
        _resp(200, {"message": {"content": "ok!"}}),
    ]
    client = OllamaClient("http://localhost:11434", "mock-model", max_retries=3, backoff_base=0.01)
    assert client.chat("sys", "user") == "ok!"
    assert mock_post.call_count == 3


@patch("nexus_formatter.ollama_client.time.sleep", lambda *_: None)
@patch("nexus_formatter.ollama_client.requests.post")
def test_gives_up_after_max_retries(mock_post):
    mock_post.return_value = _resp(500, text="down")
    client = OllamaClient("http://localhost:11434", "mock-model", max_retries=3, backoff_base=0.01)
    try:
        client.chat("sys", "user")
        assert False, "expected OllamaError"
    except OllamaError:
        pass
    assert mock_post.call_count == 3


@patch("nexus_formatter.ollama_client.requests.post")
def test_truncated_response_raises_without_retrying(mock_post):
    mock_post.return_value = _resp(
        200,
        {
            "message": {"content": '>>>NOTE_START id=0001 file="a.md"<<<\n```kot'},
            "done_reason": "length",
        },
        text="",
    )
    client = OllamaClient("http://localhost:11434", "mock-model", max_retries=3)
    try:
        client.chat("sys", "user")
        assert False, "expected OllamaTruncatedError"
    except OllamaTruncatedError as e:
        assert e.done_reason == "length"
        assert "num_ctx" in str(e)
    assert mock_post.call_count == 1
    assert client.last_done_reason == "length"


@patch("nexus_formatter.ollama_client.requests.post")
def test_num_predict_and_num_ctx_are_sent_in_options(mock_post):
    mock_post.return_value = _resp(200, {"message": {"content": "ok"}, "done_reason": "stop"})
    client = OllamaClient("http://localhost:11434", "mock-model", num_predict=4096, num_ctx=16384)
    client.chat("sys", "user")
    sent = mock_post.call_args.kwargs["json"]
    assert sent["options"]["num_predict"] == 4096
    assert sent["options"]["num_ctx"] == 16384
    assert client.last_done_reason == "stop"


@patch("nexus_formatter.ollama_client.requests.post")
def test_defaults_are_unlimited_predict_with_bounded_ctx(mock_post):
    mock_post.return_value = _resp(200, {"message": {"content": "ok"}, "done_reason": "stop"})
    client = OllamaClient("http://localhost:11434", "mock-model")
    client.chat("sys", "user")
    sent = mock_post.call_args.kwargs["json"]
    assert sent["options"]["num_predict"] == -1
    assert sent["options"]["num_ctx"] == 8192


@patch("nexus_formatter.ollama_client.requests.post")
def test_missing_model_fails_fast_without_retrying(mock_post):
    mock_post.return_value = _resp(404, text="not found")
    client = OllamaClient("http://localhost:11434", "ghost-model", max_retries=3)
    try:
        client.chat("sys", "user")
        assert False, "expected OllamaError"
    except OllamaError as e:
        assert "ghost-model" in str(e)
    assert mock_post.call_count == 1
