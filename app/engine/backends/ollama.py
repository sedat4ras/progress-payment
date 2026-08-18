"""Local inference through Ollama.

This is the backend used for the offline demo: nothing leaves the machine and
there is no per-call cost. Swapping it for `openai` changes one setting and no
application code, because both only ever answer the same narrow question -
which of these contract items is this line?
"""

from __future__ import annotations

import requests

from app.config import LLM_TIMEOUT_SECONDS, OLLAMA_HOST, OLLAMA_MODEL
from app.engine.backends.base import Candidate, Proposal
from app.engine.backends.prompt import SYSTEM_PROMPT, build_user_prompt, parse_proposal


class OllamaBackend:
    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host.rstrip("/")
        self.model = model
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            installed = {m["name"] for m in response.json().get("models", [])}
        except (requests.RequestException, ValueError, KeyError):
            return False

        return self.model in installed or any(
            m.split(":")[0] == self.model.split(":")[0] for m in installed
        )

    def propose(self, line_text: str, candidates: list[Candidate]) -> Proposal | None:
        if not candidates:
            return None

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "system": SYSTEM_PROMPT,
                    "prompt": build_user_prompt(line_text, candidates),
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 200},
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            raw = response.json().get("response", "")
        except (requests.RequestException, ValueError):
            # An unreachable model must never block a slip. The deterministic
            # result stands and the line simply goes to the review queue.
            return None

        return parse_proposal(raw, candidates, self.name)
