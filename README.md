# Project: Progress Payment — 3P

> Turning field service slips into contract-priced progress payments — with a local language model that reads, and a deterministic engine that prices.

[![CI](https://github.com/sedat4ras/progress-payment/actions/workflows/ci.yml/badge.svg)](https://github.com/sedat4ras/progress-payment/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![SQLAlchemy](https://img.shields.io/badge/ORM-SQLAlchemy%202.0-C63A2B?style=flat-square)](https://www.sqlalchemy.org/)
[![FastAPI](https://img.shields.io/badge/Web-FastAPI%20%2B%20Jinja2-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LLM](https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenAI-7C3AED?style=flat-square)](https://ollama.ai/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)](LICENSE)

---

## The problem

A facilities company serves dozens of corporate customers. Each customer has a
**contract price list** that is renegotiated every period — the same air
conditioner filter costs a different amount at the hospital than at the
shopping mall, and a different amount again in the second half of the year.

Technicians work on site and write a **service slip**: what they did, what
they used, how long it took. Someone then has to turn hundreds of these,
written in free text by people in a hurry, into **progress payments** priced
against the right contract.

That someone is a specialist, and the job is mostly lookup. This project
automates the lookup without letting a model anywhere near the arithmetic.

## The rule this design exists to enforce

**A language model never determines a price.**

```
   AI          reads the line and proposes which contract item it is
   ↓
   Engine      looks that item's price up in the contract         ← deterministic
   ↓
   Threshold   anything it is not sure about goes to a human      ← no payment created
```

A model that hallucinates a *price* produces a wrong invoice that nobody
notices. A model that hallucinates an *item code* is caught immediately,
because the code is validated against a closed list before anything is priced.
So the model is only ever allowed to make the second kind of mistake — and it
is never shown a price in the first place ([`prompt.py`](app/engine/backends/prompt.py),
[`test_backends.py`](tests/test_backends.py)).

## How a slip is processed

```
┌─────────────────────────────────────────────────────────────────────┐
│  Service slip  (customer · date · free-text lines · quantities)     │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  1. VALIDATION GATE                              no model involved  │
│     · is the customer known?                                        │
│     · was a contract active on the service date?                    │
│     · does the slip contain anything at all?                        │
│     fail ──► INVALID. No payment lines are produced.                │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. MATCHING          each layer is cheaper and safer than the next  │
│     exact  → typed the catalogue description verbatim      conf 1.00 │
│     alias  → an expert confirmed this phrasing before      conf 0.99 │
│     fuzzy  → string distance, scored down when ambiguous   conf ≤.99 │
│     llm    → last resort, picks from a closed candidate list conf ≤.90│
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. PRICING                            pure Python, no model, no API │
│     unit price ← contract    ·    net = price × qty    ·    + GST    │
│     contractual per-slip quantity ceilings enforced here            │
└───────────────────────────────┬─────────────────────────────────────┘
                    ┌───────────┴───────────┐
                    ▼                       ▼
        every line ≥ threshold      any line below it
                    │                       │
                    ▼                       ▼
                  READY              NEEDS REVIEW
                    │                (no price on the open line)
                    │                       │
                    │                       ▼
                    │              expert resolves the line
                    │              (contract item, or not billable)
                    │                       │
                    ├───────────────────────┘
                    │              last open line answered ──► READY
                    ▼
             expert signs ──────────────────────────► APPROVED
                    │                                     ▲
                    └── or takes the slip over ──► MANUAL ┘
                        (the machine was confidently wrong, or the
                         work is in no contract — the expert prices
                         it by hand and the slip says so)
```

Two properties the diagram does not show, and that the design turns on.

**A correction is not a rule.** Resolving a line fixes *that* line and nothing
else. An earlier version wrote an alias on every correction so the same wording
would match automatically next time, and that was wrong: identical field
wording legitimately means different catalogue items on different sites. The
seeded aliases are catalogue synonyms and stay; learned ones are gone.

**Every line stays actionable, including the ones the machine was sure about.**
A confidently priced line the expert has to change is the only failure mode
that can reach a customer unnoticed, so the interface keeps a correction
affordance on it and records both readings — what the machine said, what the
human said. That is what makes the silent-error number below measurable rather
than asserted.

## Results

200 synthetic slips, 481 line items, 3 customers, 6 contract periods, on a
dataset that deliberately contains typos, abbreviations, work that is in no
contract, another customer's speciality items, quantities over the
contractual ceiling, unknown customers and out-of-period dates.

| | rules only | + `qwen2.5:7b-instruct` |
|---|---|---|
| Slips priced end to end, ready to sign | 71 | 95 |
| Slips holding at least one open line | 109 | 85 |
| Slips stopped at the gate as invalid | 20 | 20 |
| Lines priced automatically | 335 / 481 (69.6%) | **378 / 481 (78.6%)** |
| Lines sent to a human | 146 (30.4%) | 103 (21.4%) |
| **Lines silently mispriced** | **0** | **0** |
| Part billed as the labour of fitting it | **0** | **0** |
| Undecidable part-or-labour lines held for a human | 12 / 12 | 12 / 12 |
| Lines queued that were actually correct | 94 | 51 |

The model's contribution is measurable and bounded: it moved 43 lines off the
expert's desk and mispriced none of them. It could not have done otherwise —
it never saw a price, and every code it returned was checked against the
contract before any of them were priced.

`Lines silently mispriced` is the only number that can hurt anyone: a line
priced automatically against the wrong contract item, which no human ever
looks at. **CI fails the build if it is not zero**
([`scripts/evaluate.py`](scripts/evaluate.py), [`ci.yml`](.github/workflows/ci.yml)).

Everything else is a workload trade-off. Lowering `PP_AUTO_APPROVE_THRESHOLD`
automates more lines and puts more wrong ones through; raising it does the
opposite. The default of `0.85` was chosen by measuring, not guessing.

<details>
<summary>Why the fuzzy matcher scores twice</summary>

The first version used RapidFuzz `WRatio` for both retrieval and confidence,
and it silently mispriced 8 lines. `WRatio` rewards partial overlap, so
`"Industrial Fan Balancing"` — work that is not in the contract at all —
scored 90% against `"Fan Motor 1/4 HP"` on the shared word *Fan*, cleared
the threshold and got a price.

Retrieval and decision want opposite things. Recall should be forgiving so a
typo still surfaces the right item; confidence should be strict so shared
vocabulary is not mistaken for the same work. The matcher now retrieves with
`WRatio` and re-scores the survivors with whole-string scorers that punish
tokens the query never accounts for. Same recall, zero mispricing.

</details>

<details>
<summary>Why a part must never be billed as the labour of fitting it</summary>

`"replaced contactor"` can mean the component or the callout that installed
it, and the two sit in the price list at very different money. A wrong item
inside the same category is an error an expert spots on review; a part billed
as labour is an error that reads plausibly and reconciles to nothing.

So category is not left to string distance. The catalogue is split into
material and labour, the matcher scores each side separately, and when the two
best candidates come from different categories and sit within
`PP_CATEGORY_AMBIGUITY_MARGIN` (15 points) of each other, the line is held for
a human no matter how high the raw confidence was.

The dataset carries 12 lines whose wording genuinely cannot settle the
question. All 12 are held on both backends. Set the margin to `0` and three of
them get priced — one at 0.851 confidence, just over the auto-approve
threshold. That is the number that earns the guard its place.

</details>

## The interface

Server-rendered FastAPI + Jinja2, hand-written CSS, one small script, no build
step. Five surfaces: a pipeline board, a slip detail, invalid slips, the
approved archive, and administration (named as out of scope rather than
missing — see [`docs/ui-spec.md`](docs/ui-spec.md) §10).

**The board** is four columns — needs review, ready, manual, approved — under
one metric strip. The two metrics next to each other are the automation rate
and the silent-error count, on purpose: neither is honest alone, because
automation is trivially inflated by lowering the threshold and the second
number is what that would cost. Cards do not drag between columns. A slip's
state is earned by lines being resolved and a signature being applied, not
assigned by a reviewer, and `finalize_draft` refuses an unresolved draft
regardless of what the UI offers.

**The slip detail** is where a decision is made. Every line is actionable,
including the ones the engine priced confidently. Showing only the queued lines
is the obvious design and the wrong one: it leaves a confident mispricing with
no route to correction, which is exactly the error that reaches a customer.

A flagged line carries the objection in plain language and resolves inline,
with the resulting price previewed before it is committed. A corrected line
shows both readings, machine above human:

```
was   MOT-001  Fan Motor 1/4 HP          $465.00   85% · fuzzy
now   SPC-302  Industrial Fan Balancing  $780.00   corrected by reviewer
```

Colour appears only in corner status tags. Everything else is weight, size and
space.

Every write is a plain form POST answered with a 303 redirect, so resolution,
take-over, manual pricing and approval all work with JavaScript switched off
and the back button never resubmits a decision. These are the actions that
move money; a duplicate approval is worse than a full page load. The one
script in the product previews what a resolution would cost and nothing
depends on it.

## Pluggable inference

The model backend is a seam, not a dependency. All three implement the same
protocol and answer the same narrow question — *which of these contract items
is this line?*

| Backend | Use | Requires |
|---|---|---|
| `rules` | CI, air-gapped sites, and the fallback whenever a model is unreachable | nothing |
| `ollama` | local demo, no per-call cost, nothing leaves the machine | Ollama + a 7B instruct model |
| `openai` | a hosted deployment where running a model on site is not an option | `OPENAI_API_KEY` |

```bash
PP_MATCHER_BACKEND=rules   python -m scripts.evaluate
PP_MATCHER_BACKEND=ollama  python -m scripts.evaluate
```

Switching is one environment variable. No application code changes, because no
application code knows which one is running. If the configured backend is not
reachable, [`get_backend`](app/engine/backends/__init__.py) falls back to
`rules` — an unavailable model degrades the automation rate, never the
correctness of a price.

## Running it

```bash
git clone https://github.com/sedat4ras/progress-payment.git
cd progress-payment

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python -m scripts.bootstrap --reset      # synthetic data + process every slip
uvicorn app.web.main:app --reload        # http://localhost:8000
```

To add the local semantic layer:

```bash
ollama pull qwen2.5:7b-instruct          # ~4.7 GB, fits in 8 GB VRAM
ollama serve
PP_MATCHER_BACKEND=ollama python -m scripts.bootstrap --reset
```

### Docker

```bash
docker build -t progress-payment .
docker run -p 8000:8000 -v progress-payment-data:/data progress-payment
```

The image ships without a model on purpose — it runs the full pipeline on
`rules` alone. Point `PP_OLLAMA_HOST` at a host running Ollama to add the
semantic layer. Nothing is fetched at runtime either: the interface is one
stylesheet and one script served from the image, so the container works with
no network at all.

## Configuration

Every knob lives in [`app/config.py`](app/config.py) and is settable by
environment variable.

| Variable | Default | What it does |
|---|---|---|
| `PP_MATCHER_BACKEND` | `rules` | which inference backend to use |
| `PP_AUTO_APPROVE_THRESHOLD` | `0.85` | below this, a line is never priced |
| `PP_NO_MATCH_CEILING` | `0.60` | below this, report "not in contract" instead of suggesting |
| `PP_FUZZY_FLOOR` | `70` | recall cutoff for candidate retrieval |
| `PP_CATEGORY_AMBIGUITY_MARGIN` | `15` | score gap below which material and labour are treated as indistinguishable |
| `PP_LLM_CONFIDENCE_CAP` | `0.90` | a model may never sound as certain as a confirmed alias |
| `PP_GST_RATE` | `0.10` | GST applied to the net total |
| `PP_DATABASE_URL` | `sqlite:///progress_payment.db` | any SQLAlchemy URL, including PostgreSQL |

## Tests

```bash
python -m pytest tests -q
```

71 tests. The suite runs with `PP_MATCHER_BACKEND=rules` and touches no
network, so the whole pipeline is verifiable with no model installed. It covers
the arithmetic, the validation gate, every route into and out of the review
queue, the category guards, the rule that a correction stays local to its line,
and the limits on what a model is allowed to influence — including the case
where a model returns an item code that does not exist.

## Synthetic data

There is no real customer data in this repository. `data/generate.py` builds
the whole dataset from a seeded RNG, so the numbers above are reproducible.
Each generated line carries the contract item it *should* match, which is what
`scripts/evaluate.py` scores against.

## Limitations

Worth being straight about, since this is a portfolio project rather than a
product:

- **The web tier is single-tenant.** There is no user model: the reviewer is a
  name in the sidebar, not an account, so there is no authentication, no
  locking and no audit of who changed what. The seam is clean — every write
  already goes through the pipeline rather than the templates — but a real
  deployment has to add it.
- **Master data is read-only.** Customers, contracts and the price list arrive
  from `data/`; an invalid slip is fixed there and reprocessed. No
  administration screen is built.
- **Input is structured.** Slips arrive as digital form data, not scans, so
  there is no OCR stage and no signature verification.
- **The dataset is Australian commercial HVAC and building maintenance,
  priced in AUD with 10% GST.** The normalisation layer and its stopword list
  are English; another language would need its own.
- **SQLite by default.** The schema is portable and `PP_DATABASE_URL` accepts
  a PostgreSQL URL, but nothing here has been tuned for concurrent writes.

## License

MIT — see [LICENSE](LICENSE).
