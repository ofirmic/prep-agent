"""Eval runner: load fixtures → synthesize → judge → write report.

Generates a timestamped markdown report. Comparing reports run-over-run is
the regression-test workflow: change a prompt, rerun, diff the scores.

Cost shape: 1 synthesize (Sonnet) + 1 judge (Sonnet) per case ≈ ~$0.05/case.
3 cases ≈ $0.15 per eval run. Cheap enough to run on every prompt change.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prep_agent.config import Settings
from prep_agent.evals.fixtures import Fixture, load_fixture
from prep_agent.evals.golden import GoldenCase
from prep_agent.evals.retrieval import RetrievalScore, score_retrieval
from prep_agent.evals.rubric import Judge, RubricResult
from prep_agent.obs.context import trace_context
from prep_agent.obs.store import TraceStore
from prep_agent.provider.factory import make_provider
from prep_agent.synthesize.generate import Synthesizer


@dataclass
class CaseResult:
    case: GoldenCase
    fixture: Fixture
    prep_markdown: str
    rubric: RubricResult
    retrieval: RetrievalScore


async def run_case(
    case: GoldenCase,
    fixtures_dir: Path,
    synthesizer: Synthesizer,
    judge: Judge,
    trace_store: TraceStore,
) -> CaseResult:
    fixture = load_fixture(fixtures_dir, case.company)
    if fixture is None:
        raise RuntimeError(
            f"No fixture for {case.company}. Run "
            f"`prep-agent eval snapshot {case.company!r}` first."
        )

    async with trace_context(trace_store, label=case.company, kind="eval_case"):
        prep = await synthesizer.synthesize(
            signals=fixture.signals,
            playbook_chunks=fixture.chunks,
        )

        rubric = await judge.grade(
            company=case.company,
            prep_doc=prep.raw_markdown,
            signals_json=fixture.signals.model_dump_json(indent=2),
            chunks_text=fixture.chunks_text(),
            golden_text=case.golden_text(),
        )

    retrieval = score_retrieval(
        company=case.company,
        expected_topics=case.retrieval.expected_topics,
        chunks=fixture.chunks,
    )

    return CaseResult(
        case=case,
        fixture=fixture,
        prep_markdown=prep.raw_markdown,
        rubric=rubric,
        retrieval=retrieval,
    )


async def run_all(
    cases: list[GoldenCase],
    fixtures_dir: Path,
    settings: Settings,
) -> list[CaseResult]:
    trace_store = TraceStore(db_path=settings.trace_db_path)
    synth_provider = make_provider(
        settings, model=settings.synthesize_model, trace_store=trace_store
    )
    synthesizer = Synthesizer(provider=synth_provider)
    judge = Judge(provider=synth_provider)

    # Run cases in parallel — each gets its own trace via ContextVar isolation.
    results = await asyncio.gather(
        *(run_case(c, fixtures_dir, synthesizer, judge, trace_store) for c in cases)
    )
    return list(results)


def write_report(results: list[CaseResult], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    path = results_dir / f"eval-{timestamp}.md"

    lines: list[str] = [f"# Eval report — {timestamp}", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append("| Company | Mean | Spec | Ground | Action | Person | Recall |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        by = r.rubric.by_axis()
        lines.append(
            f"| {r.case.company} "
            f"| {r.rubric.mean:.2f} "
            f"| {by['specificity'].score} "
            f"| {by['grounding'].score} "
            f"| {by['actionability'].score} "
            f"| {by['personalization'].score} "
            f"| {r.retrieval.recall:.0%} |"
        )

    overall_mean = (
        sum(r.rubric.mean for r in results) / len(results) if results else 0.0
    )
    lines.append("")
    lines.append(f"**Overall mean across cases: {overall_mean:.2f} / 5**")

    for r in results:
        lines.extend(_case_block(r))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _case_block(r: CaseResult) -> list[str]:
    lines = [
        "",
        "---",
        "",
        f"## {r.case.company}",
        "",
        f"_One-liner: {r.case.one_liner}_",
        "",
        "### Scores",
        "",
    ]
    for s in r.rubric.scores:
        lines.append(f"- **{s.axis.title()}**: {s.score}/5 — {s.reasoning}")
        if s.citation:
            lines.append(f"  > {s.citation}")

    if r.rubric.overall_notes:
        lines.extend(["", "### Judge's overall notes", "", r.rubric.overall_notes])

    lines.extend(
        [
            "",
            "### Retrieval",
            "",
            f"- Recall on expected topics: **{r.retrieval.recall:.0%}** "
            f"({len(r.retrieval.matched_topics)} / {len(r.retrieval.expected_topics)})",
            f"- Matched: {', '.join(r.retrieval.matched_topics) or '(none)'}",
            f"- Missed: {', '.join(r.retrieval.unmatched_topics) or '(none)'}",
        ]
    )

    if r.case.manual_scores:
        lines.extend(["", "### Judge-vs-human calibration", ""])
        for axis, manual in r.case.manual_scores.items():
            llm = r.rubric.by_axis().get(axis)
            if llm is None:
                continue
            diff = abs(llm.score - manual)
            warn = " ⚠️" if diff > 1 else ""
            lines.append(
                f"- {axis}: human={manual}, llm={llm.score}, diff={diff}{warn}"
            )

    return lines
