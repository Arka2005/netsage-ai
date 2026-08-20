"""Renders the dashboard to a self-contained HTML file, a CSV export, and the Responsible AI
log skeleton. No server, no CDN, no JavaScript — the file opens anywhere. [FR-08, FR-09]
"""

import csv
import dataclasses
import html
import io

from netsage.dashboard.metrics import DashboardData

_STYLE = """
:root { color-scheme: light dark; }
body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 2rem auto; max-width: 60rem; padding: 0 1rem; line-height: 1.5; }
h1 { margin-bottom: .25rem; }
.sub { color: #6b7280; margin-top: 0; font-size: .9rem; }
section { border: 1px solid #d1d5db; border-radius: .5rem; padding: 1rem 1.25rem; margin: 1.25rem 0; }
h2 { font-size: 1.05rem; margin: 0 0 .75rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #e5e7eb; }
th { font-weight: 600; color: #374151; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.headline { font-size: 1.6rem; font-weight: 700; }
.danger { color: #b91c1c; font-weight: 600; }
.ok { color: #15803d; }
.muted { color: #6b7280; }
.pill { display: inline-block; padding: .1rem .45rem; border-radius: .25rem;
        background: #f3f4f6; font-size: .8rem; margin-right: .25rem; }
.scroll { overflow-x: auto; }
"""


def _e(value) -> str:
    return html.escape(str(value))


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _group_table(groups, label: str) -> str:
    rows = "".join(
        f"<tr><td>{_e(g.name)}</td><td class='num'>{g.total}</td>"
        f"<td class='num'>{g.root_cause_match}</td>"
        f"<td class='num'>{'n/a' if g.root_cause_pct is None else f'{g.root_cause_pct:.0f}%'}</td>"
        f"<td class='num'>{g.osi_match}</td><td class='num'>{g.next_command_match}</td></tr>"
        for g in groups
    )
    return (
        f"<div class='scroll'><table><tr><th>{_e(label)}</th><th class='num'>cases</th>"
        "<th class='num'>root cause</th><th class='num'>%</th>"
        "<th class='num'>osi</th><th class='num'>next cmd</th></tr>"
        f"{rows}</table></div>"
    )


def render_html(data: DashboardData) -> str:
    m = data.overall
    a = data.agreement

    composition = "".join(f"<span class='pill'>{_e(k)} {v}</span>" for k, v in data.category_counts.items())
    severities = "".join(f"<span class='pill'>{_e(k)} {v}</span>" for k, v in data.severity_counts.items())

    cw = (
        f"<p class='danger'>{m.confidently_wrong} confidently wrong — "
        f"{_e(', '.join(data.confidently_wrong_cases))}</p>"
        if data.confidently_wrong_cases
        else "<p class='ok'>0 confidently wrong.</p>"
    )
    hallucinated = (
        f"<p class='danger'>Hallucinated quotes in: {_e(', '.join(data.hallucinated_cases))}</p>"
        if data.hallucinated_cases
        else "<p class='ok'>No hallucinated evidence detected.</p>"
    )
    thin = (
        f"<p class='danger'>Categories below 3 cases: {_e(', '.join(data.thin_categories))}</p>"
        if data.thin_categories
        else "<p class='ok'>Every brief-mandated fault family has at least 3 cases.</p>"
    )
    pending = (
        f"<p class='danger'>{len(data.pending_cases)} case(s) still Pending review: "
        f"{_e(', '.join(data.pending_cases))}</p>"
        if data.pending_cases
        else "<p class='ok'>Every case in this run has a human verdict.</p>"
    )

    case_rows = "".join(
        "<tr>"
        f"<td>{_e(r.case_id)}</td><td>{_e(r.category)}</td><td>{_e(r.status)}</td>"
        f"<td>{_e(r.ai_tag)}</td><td>{_e(r.expected_tag)}</td>"
        f"<td>{'✔' if r.root_cause_match else '✘'}</td>"
        f"<td>{'✔' if r.evidence_grounded else '✘'}</td>"
        f"<td class='{'danger' if r.confidently_wrong else ''}'>{_e(r.confidence_band)}</td>"
        f"<td>{_e(r.verdict)}</td>"
        "</tr>"
        for r in data.rows
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetSage AI — {_e(data.run_id)}</title><style>{_STYLE}</style></head><body>
<h1>NetSage AI — run report</h1>
<p class="sub">run <code>{_e(data.run_id)}</code> · {m.total} case(s) ·
every diagnosis requires a human verdict before it is final</p>

<section><h2>1 · Dataset composition</h2>
<p>By category: {composition}</p><p>By severity: {severities}</p></section>

<section><h2>2 · Accuracy</h2>
<p><span class="headline">{_pct(m.root_cause_accuracy)}</span> root-cause accuracy
<span class="muted">({m.root_cause_match}/{m.answered} answered; {m.abstained} abstained excluded)</span></p>
<table>
<tr><td>OSI layer match</td><td class="num">{m.osi_match}/{m.answered}</td><td class="num">{_pct(m.osi_accuracy)}</td></tr>
<tr><td>Next-command match</td><td class="num">{m.next_command_match}/{m.answered}</td><td class="num"></td></tr>
<tr><td>Parse failures</td><td class="num">{m.parse_failed}/{m.total}</td><td class="num"></td></tr>
<tr><td>Schema invalid</td><td class="num">{m.schema_invalid}/{m.total}</td><td class="num"></td></tr>
<tr><td>Backend errors</td><td class="num">{m.backend_error}/{m.total}</td><td class="num"></td></tr>
</table>
<h2 style="margin-top:1rem">Per category</h2>{_group_table(data.by_category, "category")}</section>

<section><h2>3 · AI-vs-human agreement</h2>
<p><span class="headline">{_pct(a.agreement)}</span> agreement
<span class="muted">= Accepted / (Accepted + Edited + Rejected)</span></p>
<table>
<tr><td>Accepted</td><td class="num">{a.accepted}</td></tr>
<tr><td>Edited</td><td class="num">{a.edited}</td></tr>
<tr><td>Rejected</td><td class="num">{a.rejected}</td></tr>
<tr><td class="muted">Pending (excluded from the denominator)</td><td class="num muted">{a.pending}</td></tr>
</table></section>

<section><h2>4 · Evidence quality</h2>
<p>Grounding rate: <strong>{_pct(m.grounding_rate)}</strong>
<span class="muted">({m.evidence_grounded}/{m.total} — every quote verified as a literal substring
of the case evidence)</span></p>{hallucinated}</section>

<section><h2>5 · Calibration</h2>{cw}
{_group_table(data.by_band, "confidence band")}</section>

<section><h2>6 · Difficulty</h2>{_group_table(data.by_difficulty, "difficulty")}</section>

<section><h2>7 · Coverage gaps</h2>{thin}{pending}</section>

<section><h2>Per-case detail</h2><div class="scroll"><table>
<tr><th>case</th><th>category</th><th>status</th><th>AI tag</th><th>expected</th>
<th>match</th><th>grounded</th><th>band</th><th>verdict</th></tr>
{case_rows}</table></div></section>

<p class="sub">Dataset is lab-derived and synthetic-but-realistic; accuracy here is an indicator,
not a claim of production readiness. NetSage AI advises — it never touches a device.</p>
</body></html>
"""


def render_csv(data: DashboardData) -> str:
    buffer = io.StringIO()
    fieldnames = [f.name for f in dataclasses.fields(data.rows[0])] if data.rows else ["case_id"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    for row in data.rows:
        writer.writerow(dataclasses.asdict(row))
    return buffer.getvalue()


def render_responsible_ai_log(data: DashboardData, reviews, run_id: str) -> str:
    """Skeleton entries for every Edited and Rejected verdict [FR-09, HR-06].

    The spec says this file is "generated ... and hand-expanded by the team". Two fields —
    "Why it matters" and "Mitigation applied" — are human judgement that cannot be derived from
    the data, so they are emitted as explicit TODOs rather than invented.
    """
    from netsage.review.store import EDITED, REJECTED, latest_verdicts

    rows_by_id = {row.case_id: row for row in data.rows}
    corrections = [
        review
        for review in latest_verdicts(reviews, run_id).values()
        if review.verdict in (EDITED, REJECTED)
    ]

    lines = [
        "# Responsible AI log",
        "",
        f"Generated from run `{run_id}` — every `Edited` and `Rejected` verdict.",
        "The **Why it matters** and **Mitigation applied** fields are deliberately left as TODO:",
        "they are the team's judgement, not something the tool can derive. [FR-09, HR-06]",
        "",
        f"**{len(corrections)} corrected case(s)** — the requirement is at least 5.",
        "",
    ]
    if len(corrections) < 5:
        lines += [
            f"> ⚠️ Only {len(corrections)} correction(s) recorded so far. Review more cases to meet HR-06.",
            "",
        ]

    for review in sorted(corrections, key=lambda r: r.case_id):
        row = rows_by_id.get(review.case_id)
        title = row.title if row else review.case_id
        ai_said = f"{row.ai_tag}, confidence {row.confidence} ({row.confidence_band})" if row else "(no diagnosis)"
        correct = review.corrected_root_cause or (row.expected_tag if row else "")
        failure_mode = review.failure_mode or "_(not recorded — optional for Edited verdicts)_"

        lines += [
            f"### {review.case_id} — {title}",
            f"- **AI said:** {ai_said}",
            f"- **Correct answer:** {correct or '_(not recorded)_'}",
            f"- **Verdict:** {review.verdict} — reviewer: {review.reviewer}, {review.reviewed_at_utc}",
            f"- **Failure mode:** {failure_mode}",
            f"- **Reviewer's reason:** {review.reason}",
            "- **Why it matters:** TODO — the team writes this.",
            "- **Mitigation applied:** TODO — the team writes this.",
            "",
        ]

    return "\n".join(lines)
