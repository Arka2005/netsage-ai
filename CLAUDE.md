# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This repo currently contains **specifications and data only — no implementation code yet**.
`src/` holds a single `README.md` describing the planned module layout; there is no `netsage`
package, no `cli.py`, no tests, and no build/lint/test tooling to invoke. When code is added,
follow the build order in [src/README.md](src/README.md) (steps 1–9) and update this file with
the actual commands (`pytest`, entry point, etc.) once they exist — do not invent commands before
they're real.

## What this project is

NetSage AI is an AI-assisted troubleshooter for Cisco-style Packet Tracer lab networks. It reads a
symptom + topology note + `show` command output, proposes a root cause with evidence, an OSI
layer, and a next command — then **stops**. A human reviewer must Accept, Edit, or Reject every
diagnosis before it counts as final. The system advises; it never touches a device, pushes config,
or auto-remediates.

Read `docs/` in this order to get oriented — each doc is short and cross-references the others:

1. [docs/problem_statement.md](docs/problem_statement.md) — the assignment brief, transcribed verbatim
2. [docs/project_requirements.md](docs/project_requirements.md) — requirements with stable IDs (`FR-*` functional, `DR-*` data, `AR-*` AI/prompting, `HR-*` human oversight, `NFR-*` non-functional, `CON-*` constraint) — specs and future code should reference these IDs
3. [docs/system_architecture.md](docs/system_architecture.md) — the 9-component pipeline, data flow, storage layout
4. [docs/ai_diagnosis_specification.md](docs/ai_diagnosis_specification.md) — the LLM contract in full detail
5. [docs/functional_specification.md](docs/functional_specification.md) — CLI command-by-command behavior
6. [docs/case_dataset_specification.md](docs/case_dataset_specification.md) — the `cases.csv` column contract
7. [docs/packet_tracer_integration.md](docs/packet_tracer_integration.md) — how lab scenarios become dataset rows
8. [docs/demo_plan.md](docs/demo_plan.md) — the required demo video script

## Architecture (once implemented)

Pipeline: `data/cases.csv` → rule pre-check (deterministic) → AI diagnosis (LLM) → validate/score
→ **human review gate** → dashboard + audit trail. Full diagram in
[docs/system_architecture.md](docs/system_architecture.md) §2.

Planned package layout (`src/netsage/`, see [src/README.md](src/README.md)):

- `cases.py` — `Case` dataclass and CSV loader. Exposes **two views** of a case:
  `to_prompt_context()` (symptom, topology note, show output) vs `ground_truth()` (expected fault,
  tag, layer, fix). This split is structural, not a prompting convention — ground truth must never
  reach the model.
- `rules/` — a registry of pure functions `check(case) -> list[Finding]`, one module per layer
  family (`addressing.py`, `layer2.py`, `layer3.py`, `services.py`). Rules run both before AI
  diagnosis (advisory context in the prompt) and after (consistency cross-check). Rule IDs (R01–R14)
  are catalogued in [docs/system_architecture.md](docs/system_architecture.md) §3.
- `ai/` — `client.py` defines a single `LLMClient` protocol; `ollama.py` (default, local,
  `localhost:11434`), `api.py` (hosted, key from env only), and `mock.py` (fixture replay for CI)
  all implement it. Downstream code must never branch on which backend produced a response.
  `schema.py` does JSON parsing, schema validation, and **evidence grounding** — every
  `evidence[].quote` in a diagnosis must be a verbatim substring of the case's `show_outputs` or
  `symptom`; quotes that aren't found are flagged `hallucinated_evidence`, not silently trusted.
- `scoring.py` — per-case sub-scores against ground truth, plus run-level metrics. The headline
  safety metric is **`confidently_wrong`** (high confidence *and* incorrect) — track it separately
  from ordinary wrong answers.
- `review/` — the human gate CLI. `Accepted`/`Edited`/`Rejected` verdicts; `Edited` and `Rejected`
  require a mandatory free-text reason. Resumable — re-running review on a run resumes at the
  first `Pending` case. Writes append-only to `artifacts/reviews.csv`.
- `dashboard/` — aggregates `artifacts/runs/*.jsonl` + `artifacts/reviews.csv` into a
  self-contained `artifacts/dashboard.html` (no server) plus a CSV export.
- `cli.py` — entry point: `netsage validate | check | run | review | dashboard`.

## Implementation philosophy

This is a capstone demo, not a production platform — optimize for a reliable 8-minute demo, not
scale. When two valid approaches satisfy a requirement, take the simpler one.

- Plain functions and dataclasses over class hierarchies or design patterns; no abstraction layer
  until a second concrete caller actually needs it.
- Stdlib first; no new dependency, framework, service, or architectural layer unless something in
  `docs/` explicitly requires it. Before adding one, ask "does the demo actually need this?" — if
  no, don't.
- No databases, Docker/Kubernetes, message queues, auth, or extra APIs — nothing in the
  requirements calls for any of them.
- Don't build a later phase's code early, don't duplicate logic across files, and don't create a
  new file purely for abstraction's sake.
- Every phase should be runnable and testable on its own (e.g. `netsage validate` works today with
  no other phase built yet).

## Non-negotiable design rules

These are load-bearing for the project's grading criteria and safety story — do not casually
"simplify" past them:

- **Ground truth never enters a prompt.** Enforced structurally in `cases.py` via the
  `to_prompt_context()`/`ground_truth()` split, not by prompt discipline.
- **`requires_human_review` is hard-coded `true`** in the diagnosis schema — never a value the
  model can set.
- **Evidence quotes are verified by substring match**, with whitespace normalized but no
  paraphrase tolerance. A quote not found in the source is a flag (`hallucinated_evidence`), not a
  warning to suppress.
- **No diagnosis is final without a human verdict.** Default state is `Pending`; there is no code
  path that marks a case final without going through review.
- **Store `raw_response` verbatim** before any cleanup — it's the only way to settle a dispute
  about a surprising result later.
- **Prompt changes and dataset changes never land in the same commit** (see
  [docs/ai_diagnosis_specification.md](docs/ai_diagnosis_specification.md) §9 for the full prompt
  iteration protocol) — bump `prompt_version`, re-run all 36 cases, compare before/after metrics.
- **Sampling is deterministic**: `temperature=0.0` always, for reproducibility (`NFR-04`).
- **No secrets in the repo.** API keys come from environment variables (`NETSAGE_API_KEY`) only;
  `.env` is git-ignored.

## Known scoping decisions / open items

Places where the docs in `docs/` are genuinely underdetermined and a deliberate, smallest-
defensible choice was made instead of inventing a fuller specification. Don't "fix" these by
expanding scope without raising it first — when the spec is incomplete, flag the gap rather than
silently inventing architecture or business logic.

- **`confidently_wrong` is not computed in `ai/schema.py`.** It requires comparing against ground
  truth (`root_cause_match == false`), which `parse_diagnosis()` deliberately never sees. It
  belongs in `scoring.py`, where ground truth is actually available — do not add a ground-truth
  parameter to the schema validator to compute it early.
- **`rule_conflict` is narrower than "the tag contradicts a HIGH rule finding."** The docs never
  define a rule-id → root-cause-tag mapping, and inventing one wasn't a smaller decision than
  leaving the gap. The implemented check is the one direction that's actually checkable without
  that mapping: flag `rule_conflict` when the model abstains (`insufficient_evidence`) while a
  HIGH-severity rule finding exists. Do not invent a rule-id → tag mapping to broaden this later
  without it being an explicit, separate decision.
- **The Field rules table's "no 'I have fixed' phrasing" / imperative-mood constraint on
  `fix_steps` is intentionally unenforced.** It's not in the documented Flags vocabulary
  (`hallucinated_evidence` · `unknown_tag` · `rule_conflict` · `abstained` · `confidently_wrong`),
  and a substring check would be a brittle validator prone to false rejections. Treat it as
  system-prompt guidance for the model, not a validation rule to code against.

## Dataset

`data/cases.csv` — 36 rows, 15 columns (RFC 4180, every field quoted, LF line endings, UTF-8), 10
fault categories, 36 unique `expected_root_cause` tags. Parse with a real CSV reader
(`csv.DictReader` / `pandas.read_csv`) — never split on commas, since `show_outputs` contains both
commas and embedded newlines inside quoted multi-line fields. Full column and vocabulary contract
in [docs/case_dataset_specification.md](docs/case_dataset_specification.md).

## Repo conventions

- Git line endings: `core.autocrlf false` — the CSV's LF endings must stay byte-identical (see
  `init-repo.bat`, a one-time setup script safe to ignore/delete).
- All generated artifacts are plain text (CSV/JSONL/Markdown) so they diff cleanly in git;
  `artifacts/runs/*.jsonl` and `artifacts/dashboard.html` are git-ignored as regenerable output.
- `.pkt` (Packet Tracer) files are binary and don't diff — `data/cases.csv` is the authoritative
  dataset, not the lab files.
