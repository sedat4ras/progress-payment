from app.config import MATCHER_BACKEND
from app.engine.backends.base import Candidate, MatcherBackend, Proposal
from app.engine.backends.rule_only import RuleOnlyBackend

__all__ = ["Candidate", "MatcherBackend", "Proposal", "get_backend"]


def get_backend(name: str | None = None) -> MatcherBackend:
    """Resolve a backend by name, falling back to rules-only if it is not usable."""
    name = (name or MATCHER_BACKEND).lower()

    if name == "rules":
        return RuleOnlyBackend()

    if name == "ollama":
        from app.engine.backends.ollama import OllamaBackend

        backend = OllamaBackend()
        return backend if backend.available() else RuleOnlyBackend()

    if name == "openai":
        from app.engine.backends.openai_backend import OpenAIBackend

        backend = OpenAIBackend()
        return backend if backend.available() else RuleOnlyBackend()

    raise ValueError(f"Unknown matcher backend: {name}")
