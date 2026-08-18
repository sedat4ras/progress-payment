"""Central configuration. Every knob that changes behaviour lives here."""

import os
from decimal import Decimal

DATABASE_URL = os.getenv("PP_DATABASE_URL", "sqlite:///progress_payment.db")

# Matcher backend: "rules" | "ollama" | "openai"
MATCHER_BACKEND = os.getenv("PP_MATCHER_BACKEND", "rules")

OLLAMA_HOST = os.getenv("PP_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("PP_OLLAMA_MODEL", "qwen2.5:7b-instruct")

OPENAI_MODEL = os.getenv("PP_OPENAI_MODEL", "gpt-4o-mini")

# A line at or above this confidence may be priced automatically.
# Anything below goes to the human review queue.
AUTO_APPROVE_THRESHOLD = float(os.getenv("PP_AUTO_APPROVE_THRESHOLD", "0.85"))

# RapidFuzz recall score (0-100) below which an item is not even a candidate.
FUZZY_FLOOR = int(os.getenv("PP_FUZZY_FLOOR", "70"))

# Score gap (0-100) below which two candidates in *different* categories are
# treated as indistinguishable, sending the line to a human instead of guessing.
# Wider than the ordinary ambiguity margin on purpose: billing a part as the
# labour of fitting it is the most expensive mistake this system can make.
CATEGORY_AMBIGUITY_MARGIN = float(os.getenv("PP_CATEGORY_AMBIGUITY_MARGIN", "15"))

# Strict similarity below which we report "no counterpart in the contract"
# rather than offering a suggestion the expert would only have to reject.
NO_MATCH_CEILING = float(os.getenv("PP_NO_MATCH_CEILING", "0.60"))

# How many contract items are offered to the LLM as the closed candidate set.
LLM_CANDIDATE_COUNT = int(os.getenv("PP_LLM_CANDIDATE_COUNT", "12"))

# A model is never allowed to sound more certain than a confirmed alias.
LLM_CONFIDENCE_CAP = float(os.getenv("PP_LLM_CONFIDENCE_CAP", "0.90"))

LLM_TIMEOUT_SECONDS = int(os.getenv("PP_LLM_TIMEOUT_SECONDS", "60"))

GST_RATE = Decimal(os.getenv("PP_GST_RATE", "0.10"))
CURRENCY = "AUD"
