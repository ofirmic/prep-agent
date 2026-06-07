"""Typer CLI entrypoint."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from prep_agent.calendar.auth import (
    GoogleAuthError,
    get_or_refresh_credentials,
    run_oauth_flow,
)
from prep_agent.calendar.client import GoogleCalendarClient
from prep_agent.calendar.extract import EventExtractor, looks_like_interview
from prep_agent.calendar.store import CalendarStore
from prep_agent.calendar.sync import sync as sync_calendar
from prep_agent.config import Settings
from prep_agent.evals.fixtures import load_fixture, save_fixture
from prep_agent.evals.golden import load_golden
from prep_agent.evals.runner import run_all, write_report
from prep_agent.models import CompanySignals
from prep_agent.obs.store import TraceStore
from prep_agent.pipeline import Pipeline
from prep_agent.rag.embeddings import FastEmbedEmbedder
from prep_agent.rag.ingest import discover_playbook_files, ingest
from prep_agent.rag.store import PlaybookStore, RetrievedChunk

app = typer.Typer(add_completion=False, no_args_is_help=True)
eval_app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Evaluation harness commands."
)
trace_app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Observability commands."
)
calendar_app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Calendar commands."
)
app.add_typer(eval_app, name="eval")
app.add_typer(trace_app, name="traces")
app.add_typer(calendar_app, name="calendar")
console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_GOLDEN = _REPO_ROOT / "evals" / "golden.yaml"
_DEFAULT_FIXTURES = _REPO_ROOT / "evals" / "fixtures"
_DEFAULT_RESULTS = _REPO_ROOT / "evals" / "results"


@app.command()
def research(
    company: str = typer.Argument(..., help="Company name, e.g. 'Chalk'"),
    show: bool = typer.Option(False, "--show", help="Print result to stdout"),
) -> None:
    """Research a company and write a prep doc to disk."""
    settings = Settings.from_env()
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    with console.status(f"[bold cyan]Researching {company}..."):
        pipeline = Pipeline(settings)
        prep = asyncio.run(pipeline.run(company))

    slug = _slug(company)
    out_path = settings.output_dir / f"{slug}-{date.today().isoformat()}.md"
    out_path.write_text(prep.raw_markdown, encoding="utf-8")

    console.print(f"[green]✓[/green] Wrote {out_path}")
    if show:
        console.print(Markdown(prep.raw_markdown))


@app.command("ingest")
def ingest_cmd(
    directory: Path = typer.Argument(
        Path.home() / "Documents",
        help="Directory to scan for playbook markdown files.",
    ),
) -> None:
    """Chunk + embed + store the playbook docs for RAG."""
    settings = Settings.from_env()
    files = discover_playbook_files(directory)
    if not files:
        console.print(f"[yellow]No playbook files found in {directory}[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Playbook files to ingest")
    table.add_column("file")
    table.add_column("size", justify="right")
    for f in files:
        table.add_row(f.name, f"{f.stat().st_size:,} bytes")
    console.print(table)

    with console.status("[bold cyan]Embedding and storing..."):
        embedder = FastEmbedEmbedder(model_name=settings.embedding_model)
        store = PlaybookStore(
            embedder=embedder,
            persist_dir=settings.chroma_dir,
            collection_name=settings.playbook_collection,
        )
        report = ingest(store, files)

    console.print(
        f"[green]✓[/green] Wrote {report.chunks_written} chunks "
        f"from {report.files_scanned} files "
        f"({report.files_skipped} skipped). "
        f"Total in store: {store.count()}"
    )


@app.command("query")
def query_cmd(
    text: str = typer.Argument(..., help="Search query, e.g. 'feature platform'"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
) -> None:
    """Manually query the playbook store. Useful for debugging retrieval."""
    settings = Settings.from_env()
    embedder = FastEmbedEmbedder(model_name=settings.embedding_model)
    store = PlaybookStore(
        embedder=embedder,
        persist_dir=settings.chroma_dir,
        collection_name=settings.playbook_collection,
    )
    results = store.query(text, top_k=top_k)
    if not results:
        console.print("[yellow]No results — did you run `prep-agent ingest`?[/yellow]")
        raise typer.Exit(1)

    table = Table(title=f"Top {len(results)} for: {text}")
    table.add_column("dist", justify="right")
    table.add_column("source")
    table.add_column("heading")
    table.add_column("preview")
    for r in results:
        preview = r.content[:120].replace("\n", " ")
        table.add_row(f"{r.distance:.3f}", r.source, r.heading_path, preview + "…")
    console.print(table)


@eval_app.command("snapshot")
def eval_snapshot(
    company: str = typer.Argument(..., help="Company name to snapshot."),
    fixtures_dir: Path = typer.Option(
        _DEFAULT_FIXTURES, "--fixtures-dir", help="Where to write the fixture."
    ),
) -> None:
    """Run research + retrieval for a company and cache the signals + chunks.

    Use this to freeze inputs before iterating on the synthesis prompt — evals
    are only meaningful when the inputs are stable.
    """
    settings = Settings.from_env()
    pipeline = Pipeline(settings)

    with console.status(f"[bold cyan]Capturing signals + chunks for {company}..."):
        # Re-run the upstream stages (search + extract + retrieve), skip synth.
        async def _capture() -> tuple[CompanySignals, list[RetrievedChunk]]:
            results = await pipeline._search.search_many(
                [
                    f"{company} company what they do product",
                    f"{company} engineering tech stack",
                    f"{company} funding stage employees",
                    f"{company} interview process software engineer",
                    f"{company} recent news 2026",
                ]
            )
            signals = await pipeline._extract.extract(company, results)
            chunks = pipeline._retrieve.retrieve(signals)
            return signals, chunks

        signals, chunks = asyncio.run(_capture())

    path = save_fixture(fixtures_dir, company, signals, chunks)
    console.print(
        f"[green]✓[/green] Wrote fixture: {path} "
        f"({len(signals.signals)} signals, {len(chunks)} chunks)"
    )


@eval_app.command("run")
def eval_run(
    golden_path: Path = typer.Option(_DEFAULT_GOLDEN, "--golden", help="Golden YAML."),
    fixtures_dir: Path = typer.Option(_DEFAULT_FIXTURES, "--fixtures-dir"),
    results_dir: Path = typer.Option(_DEFAULT_RESULTS, "--results-dir"),
) -> None:
    """Run the full eval harness: synthesize + judge each golden case."""
    settings = Settings.from_env()
    cases = load_golden(golden_path)

    # Validate fixtures exist before spending API budget.
    missing = [c.company for c in cases if load_fixture(fixtures_dir, c.company) is None]
    if missing:
        console.print(
            f"[red]Missing fixtures:[/red] {', '.join(missing)}. "
            f"Run `prep-agent eval snapshot <company>` for each."
        )
        raise typer.Exit(1)

    with console.status(f"[bold cyan]Grading {len(cases)} cases (parallel)..."):
        results = asyncio.run(run_all(cases, fixtures_dir, settings))

    report_path = write_report(results, results_dir)

    table = Table(title="Eval results")
    table.add_column("Company")
    table.add_column("Mean", justify="right")
    table.add_column("Spec", justify="right")
    table.add_column("Ground", justify="right")
    table.add_column("Action", justify="right")
    table.add_column("Person", justify="right")
    table.add_column("Recall", justify="right")
    for r in results:
        by = r.rubric.by_axis()
        table.add_row(
            r.case.company,
            f"{r.rubric.mean:.2f}",
            str(by["specificity"].score),
            str(by["grounding"].score),
            str(by["actionability"].score),
            str(by["personalization"].score),
            f"{r.retrieval.recall:.0%}",
        )
    console.print(table)

    overall = sum(r.rubric.mean for r in results) / len(results)
    console.print(f"\n[bold]Overall mean: {overall:.2f} / 5[/bold]")
    console.print(f"[green]✓[/green] Report: {report_path}")


@trace_app.command("list")
def traces_list(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List the most recent traces with cost + latency summary."""
    settings = Settings.from_env()
    store = TraceStore(db_path=settings.trace_db_path)
    rows = store.list_traces(limit=limit)
    if not rows:
        console.print("[yellow]No traces yet. Run `prep-agent research <company>`.[/yellow]")
        return

    table = Table(title=f"Last {len(rows)} traces")
    table.add_column("trace_id")
    table.add_column("kind")
    table.add_column("label")
    table.add_column("status")
    table.add_column("dur (s)", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("cost (USD)", justify="right")
    for r in rows:
        dur = (
            f"{(r.ended_at - r.started_at):.1f}"
            if r.ended_at is not None
            else "—"
        )
        color = {"ok": "green", "error": "red", "running": "yellow"}.get(r.status, "white")
        table.add_row(
            r.trace_id,
            r.kind,
            r.label,
            f"[{color}]{r.status}[/{color}]",
            dur,
            f"{r.total_tokens:,}",
            f"${r.total_cost_usd:.4f}",
        )
    console.print(table)

    total_cost = sum(r.total_cost_usd for r in rows)
    total_tokens = sum(r.total_tokens for r in rows)
    console.print(
        f"\n[bold]Aggregate over shown traces:[/bold] "
        f"{total_tokens:,} tokens, ${total_cost:.4f}"
    )


@trace_app.command("show")
def traces_show(
    trace_id: str = typer.Argument(..., help="Trace ID from `prep-agent traces list`."),
) -> None:
    """Show every LLM call in a trace, with stage / model / cost / latency."""
    settings = Settings.from_env()
    store = TraceStore(db_path=settings.trace_db_path)
    trace = store.get_trace(trace_id)
    if trace is None:
        console.print(f"[red]No trace with id {trace_id}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[bold cyan]Trace {trace.trace_id}[/bold cyan] — {trace.kind} | "
        f"label: {trace.label} | status: {trace.status} | "
        f"total: {trace.total_tokens:,} tok / ${trace.total_cost_usd:.4f}"
    )

    calls = store.get_calls(trace_id)
    if not calls:
        console.print("[yellow]No LLM calls recorded for this trace.[/yellow]")
        return

    table = Table(title=f"{len(calls)} LLM call(s)")
    table.add_column("#", justify="right")
    table.add_column("stage")
    table.add_column("model")
    table.add_column("in", justify="right")
    table.add_column("out", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("ms", justify="right")
    table.add_column("err")
    for i, c in enumerate(calls, start=1):
        table.add_row(
            str(i),
            c.stage,
            c.model,
            f"{c.input_tokens:,}",
            f"{c.output_tokens:,}",
            f"${c.cost_usd:.4f}",
            f"{c.latency_ms:,}",
            (c.error or "")[:30],
        )
    console.print(table)


@calendar_app.command("auth")
def calendar_auth_cmd() -> None:
    """One-time: open browser, capture OAuth token for Google Calendar."""
    settings = Settings.from_env()
    try:
        run_oauth_flow(
            client_secret_path=settings.google_client_secret_path,
            token_path=settings.google_token_path,
        )
    except GoogleAuthError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(
        f"[green]✓[/green] Token saved to {settings.google_token_path}"
    )


@calendar_app.command("list")
def calendar_list_cmd(
    days: int = typer.Option(7, "--days", "-d", help="Days ahead to scan."),
) -> None:
    """Show upcoming events that pass the interview keyword filter."""
    settings = Settings.from_env()
    creds = get_or_refresh_credentials(
        settings.google_client_secret_path, settings.google_token_path
    )
    client = GoogleCalendarClient(credentials=creds)
    events = client.list_events(
        calendar_id=settings.google_calendar_id, days_ahead=days
    )
    matches = [e for e in events if looks_like_interview(e)]

    table = Table(title=f"Upcoming interview-like events (next {days}d)")
    table.add_column("start")
    table.add_column("title")
    table.add_column("attendees")
    if not matches:
        console.print("[yellow]No interview-like events found.[/yellow]")
        return
    for e in matches:
        atts = ", ".join(a.email for a in e.attendees if not a.is_self)[:60]
        table.add_row(e.start.strftime("%Y-%m-%d %H:%M"), e.summary[:60], atts)
    console.print(table)
    console.print(
        f"\n[dim]Scanned {len(events)} events, {len(matches)} matched the keyword filter.[/dim]"
    )


@calendar_app.command("sync")
def calendar_sync_cmd(
    days: int = typer.Option(7, "--days", "-d"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify, don't generate."),
    confidence: float = typer.Option(0.6, "--confidence", "-c"),
) -> None:
    """Find new interview events, classify them, and generate prep docs."""
    settings = Settings.from_env()
    creds = get_or_refresh_credentials(
        settings.google_client_secret_path, settings.google_token_path
    )
    calendar_client = GoogleCalendarClient(credentials=creds)
    calendar_store = CalendarStore(db_path=settings.trace_db_path)
    pipeline = Pipeline(settings)
    # Reuse the same TracedAnthropic the pipeline holds so calendar_extract
    # calls land in the same trace store.
    event_extractor = EventExtractor(provider=pipeline.extract_provider)

    self_emails: list[str] = []  # Optional override; calendar API already tags `self`.

    with console.status(f"[bold cyan]Syncing calendar (next {days}d)..."):
        report = asyncio.run(
            sync_calendar(
                calendar_client=calendar_client,
                event_extractor=event_extractor,
                pipeline=pipeline,
                calendar_store=calendar_store,
                output_dir=settings.output_dir,
                calendar_id=settings.google_calendar_id,
                self_emails=self_emails,
                days_ahead=days,
                confidence_threshold=confidence,
                dry_run=dry_run,
            )
        )

    table = Table(title=f"Sync result ({'dry-run' if dry_run else 'live'})")
    table.add_column("action")
    table.add_column("start")
    table.add_column("event")
    table.add_column("company")
    table.add_column("conf", justify="right")
    table.add_column("prep")
    for a in report.actions:
        table.add_row(
            a.action,
            a.event.start.strftime("%Y-%m-%d %H:%M"),
            a.event.summary[:50],
            a.classification.company or "—",
            f"{a.classification.confidence:.2f}",
            Path(a.prep_path).name if a.prep_path else "—",
        )
    console.print(table)
    console.print(
        f"\n[dim]Events seen: {report.events_seen}, "
        f"already processed: {report.events_already_processed}, "
        f"generated this run: {len(report.generated)}.[/dim]"
    )


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8501, "--port", "-p"),
) -> None:
    """Launch the Streamlit UI (home, history, observability)."""
    app_path = Path(__file__).parent / "ui" / "app.py"
    if not app_path.exists():
        console.print(f"[red]UI app not found at {app_path}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Launching Streamlit at http://localhost:{port}[/green]")
    # Inherit the current env (incl. API keys) into the streamlit subprocess.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
        env=os.environ.copy(),
        check=False,
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


if __name__ == "__main__":
    app()
