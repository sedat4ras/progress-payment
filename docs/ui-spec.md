# 3P — Interface Specification

Binds the information architecture in [`domain-model.md`](domain-model.md) §5 to
a concrete visual model. Framework-agnostic: every rule here is about structure
and hierarchy, not about a particular widget library.

The reference that set the direction is a CRM dashboard. What was taken from it
is the *system*, not the content: a pipeline board as the primary surface, one
metric strip above it, selection expressed by inversion rather than colour, and
a counted sidebar. What was rejected from it is listed in §7.

---

## 1. Visual language

The reference is almost colourless, and that is the point. Colour carries
meaning only where meaning is scarce; everywhere else, hierarchy is built from
weight, size and space.

| Token | Value | Used for |
|---|---|---|
| Canvas | warm off-white | Page background |
| Surface | white | Cards, panels |
| Surface inverted | near-black | Selected card, primary button |
| Hairline | 1px, light warm grey | Every border. No shadows |
| Accent | one pale sage | The metric strip, and nothing else |
| Radius | 12px surfaces, 8px pills, 6px chips | |
| Type | one sans family, four sizes | 30px hero numbers · 14px semibold titles · 13px muted body · 11px meta |
| Icons | 16px, 1.5px stroke, line only | |

Three rules that keep it from drifting:

1. **One accent region per screen.** The sage strip is it. A second tinted panel
   anywhere makes both look arbitrary.
2. **No shadows, no gradients.** Separation is a hairline border or whitespace.
3. **Colour appears only in status tags**, at 10px, in a card corner — never as
   a filled alert panel, never as body text.

### 1.1 Status tag palette

The only colour in the application. Small, uppercase, one per card.

| State | Tone | Reads as |
|---|---|---|
| NEEDS REVIEW | amber | The machine knows it does not know |
| READY | neutral grey | Nothing is wrong, sign it |
| MANUAL | violet | A human took this over |
| APPROVED | green | Closed |
| INVALID | red | Master data is missing |

At line level inside a slip, the same palette marks a flagged line, a corrected
line and a manually priced line. Nothing else in the product is coloured.

---

## 2. Screen inventory

```
Pipeline          the board — primary surface, the screen that tells the story
Slip detail       the work surface, opened from any card
Invalid           master-data failures, worked separately
Approved          archive, read-only, searchable
Administration    customers, contracts, price list, engine settings — see §10
```

Five screens. The reference's sidebar carries a main nav, a project list and a
member list; ours carries a main nav, a customer list, and the signed-in
reviewer at the bottom. Same skeleton, our nouns.

### 2.1 Sidebar

```
3P                                    brand mark, text only, no logo

Pipeline                     42       total slips in flight
Invalid                       3       count only shown when non-zero
Approved                    128

Customers                             section label
  Southbank Central          18
  St Marlow Private          14
  Kingsford Metals           10       clicking filters the board

─────────────────────────────
Reviewer name                         signed-in user, bottom-anchored
Progress Payment Specialist
```

Counts are the whole point of this pattern in the reference, and they carry
more weight here than they do in a CRM: a number next to *Invalid* is a
data-quality alarm, and a number next to a customer is that customer's backlog.

---

## 3. Metric strip

One horizontal band above the board, in the accent tone, four slots. The
reference uses bar chart · gauge · number · money, and that division of shapes
is worth keeping because each shape suits a different kind of quantity.

`domain-model.md` §5.2 lists eight candidate components. Four fit. The
selection is not arbitrary — these are the two numbers that sell the product
and the two that run the day:

| Slot | Shape | Metric | Why this one |
|---|---|---|---|
| 1 | Bar chart | Exception breakdown by flag code | Answers *why* work is stuck. Bars because the comparison between causes is the information |
| 2 | Radial gauge | **Automation rate** — lines priced with no human touch | A proportion of a whole, and the first thing a buyer looks at |
| 3 | Large number | **Silent errors** — confidently priced lines a reviewer had to correct | The trust number. Rendered as a large `0` with *in 1,240 priced lines* beneath it |
| 4 | Money | Value pending | Confirmed plus at-stake across everything unapproved |

Slots 2 and 3 are adjacent on purpose. They are the pair that justifies the
product and neither is honest alone: automation rate is trivially inflated by
lowering the confidence threshold, and slot 3 is what that would cost. Read
together they say *it did 84% of the work and got none of it quietly wrong.*

A large `0` is a stronger object than a gauge pinned at 100%, and it degrades
truthfully — the day it reads `3`, the claim adjusts itself without anyone
rewriting a README. Cross-category errors (domain model §2.5) appear in the
same slot as a second line, and only when non-zero.

**Slip counts are deliberately absent from the strip.** The board's column
chips sit a hundred pixels below and already carry them; a strip slot repeating
the same figure spends a quarter of the most valuable band on the screen to say
nothing new.

Slots 1, 3 and 4 are clickable and filter the board. Slot 2 is not — it is a
statement, not a query.

---

## 4. The pipeline board

Four columns, left to right, matching the lifecycle in `domain-model.md` §2.1:

```
Needs Review  │  Ready  │  Manual  │  Approved
     12       │   17    │    3     │    128
```

Each column header carries a count chip and a sort toggle — by age or by value,
the two ways a reviewer prioritises.

INVALID is deliberately **not** a column. It is not a stage of the workflow; it
is a slip that never entered one, and it is resolved by fixing master data
rather than by reviewing anything. It lives in the sidebar.

### 4.1 Cards do not drag

This is the one place the reference's interaction model must be rejected
outright. In a CRM you drag a deal between stages because the stage *is* a
human judgement. Here a slip's state is earned: it moves right by lines being
resolved and a signature being applied, and the code already refuses to approve
a draft with an unresolved line (`finalize_draft`). A drag handle would offer a
transition the domain forbids.

Movement happens through the slip detail. The board reports; it does not edit.

### 4.2 Card anatomy

Collapsed — everything needed to triage without opening:

```
┌──────────────────────────────┐
│ SLP-2291            [tag] ⋮  │   slip number, status tag, menu
│ Southbank Central            │   customer
│ 6 lines · 2 need review      │   composition, muted
│                              │
│ ⌗ 14 Apr        $ 1,284.50   │   service date · value
└──────────────────────────────┘
```

The reference puts two anonymous icon-and-count pairs in the footer. Ours are
named quantities, because a reviewer choosing what to open next is choosing on
date and money, not on a comment count.

Expanded — the selected card inverts to near-black, as in the reference, and
reveals what triage cannot show:

```
┌──────────────────────────────┐
│ SLP-2291            [tag] ⋮  │
│ Southbank Central            │
│ 6 lines · 2 need review      │
│                              │
│ Contract  SBC-2026-A         │   the contract in force on the service date
│ Technician  Liam Harrison    │
│                              │
│ Confirmed        $ 1,284.50  │   priced and settled
│ Pending            $ 412.00  │   blocked lines, at stake
│                              │
│ ⌗ 14 Apr      Open slip →    │
└──────────────────────────────┘
```

The confirmed/pending split is the fix for gap 7 in the domain model. Today a
slip in review reports a total of zero, which tells the reviewer nothing about
whether it is worth opening.

---

## 5. Slip detail

The work surface. The board is scannable; this is where a decision is made.

Header carries the five questions from `domain-model.md` §5.4 group 1 and 2:
status, contract in force, service date, technician, and the confirmed/pending
totals.

Below it, lines in slip order — **every one of them actionable**, which is the
single most important change from the Streamlit build. There, a line the
machine priced confidently was skipped entirely, so a silent mispricing had no
route to correction and UC-8 was impossible.

Three line presentations, distinguished by weight rather than by panel colour:

**Priced.** One row, low contrast. Raw text, matched item, method and
confidence, the arithmetic. A quiet *Correct* affordance on hover — present but
not soliciting.

**Flagged.** Raised contrast, amber corner tag, the flag message in plain
language, and the resolution control inline: a contract item selector, the
resulting price previewed live before committing, and a *Not billable* option.
The learn-this-phrasing checkbox is **removed** — see domain model §2.4.

**Corrected.** Shows both readings, machine and human, one above the other:

```
was   MOT-001  Fan Motor 1/4 HP        $465.00   85% · fuzzy
now   SPC-302  Industrial Fan Balancing $780.00   corrected by reviewer
```

This is group 5 of §5.4, it is what makes the silent-error metric computable,
and it is the most persuasive thing on the screen: it is the product admitting
a mistake, in public, with the evidence attached.

Footer: totals, and the approve control — disabled with a plain-language reason
whenever any line is unresolved, never silently inert.

---

## 6. Empty and edge states

The reference shows only a full, healthy board. Four states it does not cover
and that decide whether the product feels finished:

| Situation | Treatment |
|---|---|
| Column empty | One muted line stating what would appear there. No illustration |
| Board empty | Points at the bootstrap script rather than showing a bare grid |
| Long description | Two lines, then truncate. The card is a summary, not the record |
| Backend unavailable | Ollama or OpenAI unreachable is a sidebar-level notice, not a per-card error. The pipeline still runs on rules; the user must know the engine is degraded, not that a card failed |

---

## 7. Taken, and not taken

| Reference pattern | Decision |
|---|---|
| Kanban board as primary surface | **Taken.** Left-to-right reads as the lifecycle, which is exactly the story to tell a buyer |
| Metric strip in one accent band | **Taken.** Forces four metrics out of eight candidates, which is good discipline |
| Selection by dark inversion | **Taken.** Gives emphasis without spending colour |
| Counted sidebar with a grouped section | **Taken**, with customers in place of projects |
| Drag between columns | **Rejected.** State is earned, not assigned (§4.1) |
| Anonymous icon-count pairs on cards | **Rejected.** Replaced with date and value, the two fields a reviewer triages on |
| Member list with avatars | **Rejected.** There is no user model, and inventing one to fill a sidebar is scope for decoration |
| Per-card overflow menus everywhere | **Kept minimal.** One menu, on the card, with reprocess and open |

---

## 8. Delivery

**FastAPI + Jinja2 templates, hand-written CSS, no build step.** Streamlit is
retired.

The reasoning is not only visual. Streamlit's rerun cycle, widget model and
default focus styling all work against a board of this density, so the fidelity
above would have been reached by fighting the framework rather than using it.
But the larger argument is what the artefact becomes: a real HTTP service is a
far better substrate for the rest of the roadmap than a Streamlit script —
it containerises honestly, it has endpoints worth testing in CI, and it is
something a security pipeline can meaningfully be pointed at.

The blast radius is contained. `app/models.py`, `app/pipeline.py` and
everything under `app/engine/` are pure and already framework-agnostic; none of
it changes for this. Only `app/ui/` was discarded.

### 8.1 Two choices this section originally got wrong

**No HTMX.** Every write is a plain form POST answered with a 303 redirect.
Line resolution, take-over, manual pricing and approval all work with
JavaScript switched off, and the back button never resubmits a decision. That
matters more here than partial rendering does: these are the actions that move
money, and the one thing worse than a slow page is an approval that fires
twice. The single script in the product previews what a resolution would cost
before it is committed, and nothing depends on it.

**No Tailwind.** The visual language in §1 is nine tokens and about four
hundred lines of CSS. A utility framework would have bought nothing that
`:root` custom properties do not, and would have added either a CDN request at
runtime or a Node toolchain at build time. The container image stays Python
only and works offline.

## 9. Resolved

**Does the board paginate?** No — a column is a work queue, not a list. Each
column draws the top twelve under the active sort (Approved draws six and hands
off to the archive) while its header reports the true count, so the number a
reviewer plans against is never the number of cards on screen. Reaching the
rest is what the sort toggle and the customer filter are for.

## 10. Not built

**Administration.** §2 lists it as the fifth screen: customers, contracts,
price list, engine settings. Nothing in the demo edits master data — the
catalogue arrives from `data/`, and an invalid slip is fixed there and
reprocessed. The screen is named here so its absence is a decision rather than
an oversight.
