"""Minimal client for a local Ollama server, with automatic retry/backoff."""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when the model cannot produce a usable response."""


class OllamaTruncatedError(OllamaError):
    """Raised when the model stopped because it hit its output token limit.

    Retrying the same prompt will truncate again, so callers should not
    retry; they should raise num_predict or shrink the batch instead.
    """

    def __init__(self, message: str, done_reason: str = "length", raw: str = ""):
        super().__init__(message)
        self.done_reason = done_reason
        self.raw = raw


class OllamaClient:
    def __init__(self, base_url: str, model: str, temperature: float = 0.2,
                 timeout: int = 180, max_retries: int = 3, backoff_base: float = 2,
                 num_predict: int = -1, num_ctx: Optional[int] = 8192):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        # Ollama's default num_predict is small (~128); long notes with code
        # blocks blow past it and get cut off mid-fence. -1 means "generate
        # until the model stops or num_ctx is reached".
        self.num_predict = num_predict
        # num_ctx bounds the KV cache. With num_predict=-1 the model can
        # generate up to num_ctx tokens, so this is what actually caps
        # memory use. 8192 fits comfortably in 8 GB VRAM with a 3B model.
        self.num_ctx = num_ctx
        # Populated after each chat() call so callers can inspect why the
        # model stopped ("stop", "length", ...).
        self.last_done_reason: Optional[str] = None

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        options = {"temperature": self.temperature, "num_predict": self.num_predict}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": options,
        }
        self.last_done_reason = None

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = e
                logger.warning("Ollama unreachable (attempt %d/%d): %s", attempt, self.max_retries, e)
            else:
                if resp.status_code == 404:
                    # Not retryable: the model just isn't pulled.
                    raise OllamaError(
                        f"Model '{self.model}' not found on the Ollama server. "
                        f"Try: ollama pull {self.model}"
                    )
                if resp.status_code >= 500:
                    last_error = OllamaError(f"Server error {resp.status_code}: {resp.text[:200]}")
                    logger.warning("Ollama server error (attempt %d/%d): %s",
                                   attempt, self.max_retries, last_error)
                elif resp.status_code >= 400:
                    raise OllamaError(f"Bad request ({resp.status_code}): {resp.text[:300]}")
                else:
                    data = resp.json()
                    done_reason = data.get("done_reason") or ""
                    self.last_done_reason = done_reason or None
                    content = (data.get("message") or {}).get("content", "").strip()
                    if done_reason == "length":
                        # Not retryable: same prompt + same budget = same cut-off.
                        # With num_predict=-1 this means num_ctx was exhausted,
                        # so the fix is a larger num_ctx or a smaller batch.
                        raise OllamaTruncatedError(
                            f"Model output truncated (done_reason=length, "
                            f"{len(content)} chars). Increase num_ctx or "
                            f"reduce batch size.",
                            done_reason=done_reason,
                            raw=content,
                        )
                    if content:
                        return content
                    last_error = OllamaError("Model returned an empty response.")
                    logger.warning("Empty response (attempt %d/%d)", attempt, self.max_retries)

            if attempt < self.max_retries:
                wait = self.backoff_base ** attempt
                logger.info("Retrying in %.0fs...", wait)
                time.sleep(wait)

        raise OllamaError(f"Failed after {self.max_retries} attempts: {last_error}")
