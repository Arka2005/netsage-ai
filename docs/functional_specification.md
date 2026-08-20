# Functional Specification — NetSage AI

What the system does, command by command, screen by screen. Requirement IDs in brackets refer to
[`project_requirements.md`](project_requirements.md).

---

## 1. Actors

| Actor | Description | Can do |
| --- | --- | --- |
| **Case author** | Student who builds a Packet Tracer lab and records the fault | Add/edit rows in `cases.csv` |
| **Operator** | Student who runs the pipeline | Run `validate`, `check`, `run`, `dashboard` |
| **Reviewer** | Human in the loop (a different team member from the operator, where possible) | Issue `Accepted` / `Edited` / `Rejected` verdicts |
| **Assessor** | Instructor evaluating the project | Read the dashboard, the reviews CSV and the Responsible AI log |

NetSage AI itself is deliberately **not** an actor with authority. It produces recommendations.

---

## 2. Command surface

### 2.1 `netsage validate`

Checks `data/cases.csv` against the schema contract. [FR-01, DR-01…DR-07]

**Behaviour**

- Verifies all 15 columns are present and correctly ordered.
- Verifies `case_id` is unique and matches `NS-\d{3}`.
- Verifies enum fields: `severity ∈ {Low, Medium, High, Critical}`,
  `difficulty ∈ {Easy, Medium, Hard}`, `osi_layer` matches the allowed layer tokens.
- Verifies no field required by DR-03 is blank.
- Warns if any fault family from DR-02 has fewer than 3 cases.

**Output (example)**

```
✔ 36 cases loaded from data/cases.csv
✔ schema OK — 15/15 columns
✔ case_id unique
✔ coverage: VLAN 4 · Gateway 4 · DHCP 4 · DNS 4 · Routing 4 · ACL 4 · NAT 4 · Wireless 4 · Switching 2 · Physical 2
✔ severity: Critical 8 · High 16 · Medium 11 · Low 1
exit 0
```

**Exit codes:** `0` valid · `1` schema violation · `2` file missing/unreadable.

---

### 2.2 `netsage check --case NS-021 | --all`

Runs the deterministic rule engine only. No model, no network. [FR-02, FR-04]

**Behaviour**

- Loads the case, runs every registered rule, prints findings ordered by severity.
- Each finding shows the rule ID, a one-line message, and the exact evidence line it fired on.
- With `--all`, prints a per-rule hit table so the team can see which rules are dead weight.

**Output (example, NS-021 — ACL applied in the wrong direction)**

```
NS-021  ACL applied in the wrong direction   [ACL · High]

  R11_acl_zero_match      HIGH    ACL 110 line 10 has 0 matches but is the stated intent
      evidence: " 10 deny ip 10.10.30.0 0.0.0.255 10.10.99.0 0.0.0.255 (0 matches)"
  R11_acl_zero_match      INFO    ACL 110 applied 'in' on Gi0/0.99 — source subnet is not 10.10.99.0/24
      evidence: "  Inbound  access list is 110"

2 findings · 0 errors
```

**Exit codes:** `0` completed (findings are not failures) · `1` case not found · `3` rule crash.

---

### 2.3 `netsage run`

The diagnosis pipeline. [FR-03…FR-07, FR-10, FR-11, AR-01…AR-08]

```
netsage run --backend {ollama|api|mock} --model <name> [--case NS-021 | --all]
            [--temperature 0.0] [--prompt prompts/diagnose_prompt.md] [--run-id <id>]
```

**Per-case sequence**

1. Build prompt context from `Case.to_prompt_context()` — ground truth is structurally excluded. [DR-06]
2. Attach rule pre-check findings as an advisory block in the user message.
3. Call the selected backend at the configured temperature.
4. Parse and validate the JSON response. On malformed JSON, issue exactly one repair retry with
   the parser error appended; on a second failure, record `status: parse_failed` and move on. [AR-08]
5. Verify evidence grounding: every `evidence[].quote` must be a substring of the case's
   `show_outputs` or `symptom` after whitespace normalisation. Unmatched quotes →
   `hallucinated_evidence`. [AR-03]
6. Run post-checks: does the claimed `root_cause_tag` contradict any rule finding?
7. Score against ground truth. [FR-05]
8. Append one JSON object to `artifacts/runs/<run_id>.jsonl`. [FR-07]

**Console output (example, NS-021)**

```
NS-021  ACL applied in the wrong direction
  AI root cause : acl_wrong_direction              [expected: acl_wrong_direction]     ✔
  OSI layer     : L3/L4                            [expected: L3/L4]                   ✔
  Confidence    : 0.82 (high)
  Evidence      : 2/2 quotes grounded                                                  ✔
  Next command  : show ip interface Gi0/0.99 | include access list                     ✔
  Verdict       : PENDING HUMAN REVIEW
```

The last line is not decoration. No case is final here. [HR-01]

**Run summary**

```
run 20260820T1130Z-ollama-llama3.1-8b-v1.2   36 cases
  root cause match   28/36  (77.8%)
  osi layer match    31/36  (86.1%)
  evidence grounded  34/36  (94.4%)
  abstained           2/36
  parse failures      0/36
  confidently wrong   3      ← review these first
all 36 cases are PENDING human review → run: netsage review --run <run_id>
```

---

### 2.4 `netsage review --run <run_id>`

The mandatory human gate. [FR-06, HR-01…HR-05]

**Per-case screen**

```
────────────────────────────────────────────────────────────────────
NS-022  Implicit deny drops return traffic        ACL · Critical · Hard
────────────────────────────────────────────────────────────────────
SYMPTOM
  Hosts behind R1 can send traffic out to the internet but no replies
  come back...

SHOW OUTPUT (evidence)
  R1# show access-lists 101
   10 permit tcp any host 203.0.113.2 eq 22 (0 matches)
   ...

RULE FINDINGS
  R11_acl_zero_match  HIGH  two permit lines with 0 matches

AI DIAGNOSIS                              GROUND TRUTH
  root cause : acl_blocks_dns        ✘     acl_blocks_return_traffic
  osi layer  : L4                    ✔     L4
  confidence : 0.79 (high)                 ← confidently wrong
  evidence   : 2/2 grounded          ✔
  next cmd   : show access-lists 101 ✔     show access-lists 101

  fix_steps  : 1. Add permit udp ... eq 53
               2. Re-apply the ACL

[A]ccept   [E]dit   [R]eject   [S]kip   [Q]uit
>
```

**Rules of the gate**

- `Accepted` — the diagnosis is correct and actionable as written.
- `Edited` — substantially right but needs correction; the reviewer supplies the corrected root
  cause and/or fix, **and a mandatory reason**. [HR-03]
- `Rejected` — wrong or unsafe; **mandatory reason** and a failure-mode category. [HR-03]
- `Skip` leaves the case `Pending`. Pending cases are excluded from "final" counts and are
  listed loudly on the dashboard so nothing quietly slips through. [HR-01]
- Reviewer name and UTC timestamp are stamped on every verdict. [HR-04]
- The session is resumable; re-running `review` on the same run resumes at the first `Pending`.

**Writes** one row to `artifacts/reviews.csv`:

```
run_id, case_id, verdict, reviewer, reviewed_at_utc, failure_mode,
corrected_root_cause, corrected_fix, reason
```

---

### 2.5 `netsage dashboard --run <run_id>`

Generates `artifacts/dashboard.html` plus a CSV export. [FR-08]

**Panels**

| Panel | Content |
| --- | --- |
| Dataset composition | Case counts by category and by severity (the brief's "counts by issue type") |
| Accuracy | Root-cause match, OSI match, next-command match — overall and per category |
| Agreement | AI-vs-human: Accepted / Edited / Rejected split, and agreement rate |
| Evidence quality | Grounding rate; list of cases with hallucinated quotes |
| Calibration | Confidence vs correctness; the confidently-wrong list called out in red |
| Difficulty | Accuracy split by Easy / Medium / Hard |
| Coverage gaps | Categories below 3 cases; cases still `Pending` review |

**Headline metric — AI-vs-human agreement rate**

```
agreement = Accepted / (Accepted + Edited + Rejected)
```

Pending cases are deliberately excluded from the denominator and reported separately, so an
unreviewed run can never inflate the score.

---

### 2.6 Responsible AI log

`artifacts/responsible_ai_log.md` is generated from every `Edited` and `Rejected` verdict and
hand-expanded by the team. [FR-09, HR-06] Minimum 5 entries. Each entry:

```markdown
### NS-022 — Implicit deny drops return traffic
- **AI said:** acl_blocks_dns, confidence 0.79 (high)
- **Correct answer:** acl_blocks_return_traffic
- **Verdict:** Rejected — reviewer: <name>, 2026-08-20T11:42Z
- **Failure mode:** pattern-matched on a familiar ACL scenario and ignored the direction of the
  blocked flow
- **Why it matters:** a junior engineer following this would add a DNS permit, see no change,
  and lose 20 minutes
- **Mitigation applied:** added a worked ACL return-traffic example to the prompt; added rule
  R11 to flag permit lines with 0 matches
```

**Failure-mode vocabulary:** `wrong_layer` · `plausible_but_unsupported` · `hallucinated_evidence` ·
`overconfident` · `incomplete_fix` · `unsafe_recommendation` · `missed_security_implication` ·
`should_have_abstained`.

---

## 3. Diagnosis response contract

Summarised here; authoritative version in
[`ai_diagnosis_specification.md`](ai_diagnosis_specification.md).

```json
{
  "case_id": "NS-021",
  "root_cause": "ACL 110 is applied inbound on the server subinterface...",
  "root_cause_tag": "acl_wrong_direction",
  "osi_layer": "L3/L4",
  "confidence": 0.82,
  "confidence_band": "high",
  "evidence": [
    { "quote": "  Inbound  access list is 110",
      "source": "show_outputs",
      "why": "The ACL is bound inbound on the interface facing the destination, not the source." }
  ],
  "next_command": ["show ip interface Gi0/0.99 | include access list"],
  "fix_steps": ["Remove ip access-group 110 in from Gi0/0.99", "Apply it inbound on Gi0/0.30"],
  "verification_steps": ["Re-test from a guest host", "Confirm the deny line increments"],
  "risk_notes": "Applying the ACL outbound on the server subinterface would also filter...",
  "requires_human_review": true
}
```

`requires_human_review` is hard-coded `true`. It is not a field the model gets to negotiate. [HR-05]

---

## 4. Error handling

| Condition | Behaviour |
| --- | --- |
| `cases.csv` missing | Abort with exit 2 and the expected path |
| Schema violation | Abort before any model call; list every offending row |
| Backend unreachable (Ollama not running) | Clear message with the start command; exit 4 |
| Model returns non-JSON | One repair retry, then `parse_failed`; run continues |
| Evidence quote not found in the case | Flag `hallucinated_evidence`; keep the diagnosis but score it down |
| Rule raises an exception | Log rule ID + traceback, continue other rules, mark run degraded |
| Review interrupted | Verdicts already written are preserved; the run resumes at the first `Pending` |
| No API key when `--backend api` | Refuse to start; suggest `--backend ollama` or `--backend mock` |

---

## 5. Out of scope (explicit non-goals)

- Connecting to real or simulated devices over SSH/Telnet.
- Pushing configuration or auto-remediating anything.
- Parsing `.pkt` binary files (see [`packet_tracer_integration.md`](packet_tracer_integration.md)).
- Multi-user accounts, authentication, or a web service. The reviewer runs a local CLI.
- Fine-tuning a model. NetSage AI is a prompting + verification project, not a training project.
