"""Minimal client for a local Ollama server, with automatic retry/backoff."""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when the model cannot produce a usable response."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, temperature: float = 0.2,
                 timeout: int = 180, max_retries: int = 3, backoff_base: float = 2):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": self.temperature},
        }

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
                    content = (data.get("message") or {}).get("content", "").strip()
                    if content:
                        return content
                    last_error = OllamaError("Model returned an empty response.")
                    logger.warning("Empty response (attempt %d/%d)", attempt, self.max_retries)

            if attempt < self.max_retries:
                wait = self.backoff_base ** attempt
                logger.info("Retrying in %.0fs...", wait)
                time.sleep(wait)

        raise OllamaError(f"Failed after {self.max_retries} attempts: {last_error}")
