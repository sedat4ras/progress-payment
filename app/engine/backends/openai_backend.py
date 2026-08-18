"""Hosted inference, for a deployment where running a model locally is not an option.

Identical contract to the Ollama backend: a closed candidate list in, one code
or an abstention out. Prices are never sent and never returned.
"""

from __future__ import annotations

import os

import requests

from app.config import LLM_TIMEOUT_SECONDS, OPENAI_MODEL
from app.engine.backends.base import Candidate, Proposal
from app.engine.backends.prompt import SYSTEM_PROMPT, build_user_prompt, parse_proposal

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIBackend:
    name = "openai"

    def __init__(self, model: str = OPENAI_MODEL):
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")

    def available(self) -> bool:
        return bool(self.api_key)

    def propose(self, line_text: str, candidates: list[Candidate]) -> Proposal | None:
        if not candidates or not self.api_key:
            return None

        try:
            response = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(line_text, candidates)},
                    ],
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError):
            return None

        return parse_proposal(raw, candidates, self.name)
