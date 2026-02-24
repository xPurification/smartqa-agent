"""CLI interface using Click with Rich terminal output."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from smartqa import __version__
from smartqa.config import Settings, get_settings
from smartqa.logging_config import setup_logging
from smartqa.models import QAReport, RiskLevel, Severity, TestPlan, TestStatus

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="smartqa")
def cli() -> None:
    """SmartQA Agent — AI-Powered Autonomous Test Automation."""


@cli.command()
@click.option("--url", required=True, help="URL of the web application to analyze.")
@click.option("--output", "-o", default=None, help="Write JSON test plan to file.")
def analyze(url: str, output: str | None) -> None:
    """Analyze a web application and generate a test plan."""
    settings = get_settings()
    setup_logging(settings.log_level)
    _validate_api_key(settings)

    from smartqa.agent import SmartQAAgent

    agent = SmartQAAgent(settings=settings)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Analyzing page and generating test plan...", total=None)
        test_plan = agent.analyze(url)

    _render_test_plan(test_plan)

    if output:
        _write_json(test_plan.model_dump(mode="json"), output)


@cli.command("run")
@click.option("--url", required=True, help="URL of the web application to test.")
@click.option("--output", "-o", default=None, help="Write JSON report to file.")
def run_tests(url: str, output: str | None) -> None:
    """Run the full QA pipeline: analyze, generate, execute, and report."""
    settings = get_settings()
    setup_logging(settings.log_level)
    _validate_api_key(settings)

    from smartqa.agent import SmartQAAgent

    agent = SmartQAAgent(settings=settings)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Running full QA pipeline...", total=None)
        report = agent.run(url)

    _render_qa_report(report)

    if output:
        _write_json(report.model_dump(mode="json"), output)


@cli.command()
@click.option("--host", default=None, help="Bind host (default from config).")
@click.option("--port", default=None, type=int, help="Bind port (default from config).")
def serve(host: str | None, port: int | None) -> None:
    """Launch the FastAPI service."""
    settings = get_settings()
    setup_logging(settings.log_level)

    import uvicorn

    bind_host = host or settings.api_host
    bind_port = port or settings.api_port

    console.print(
        Panel(
            f"[bold green]SmartQA API v{__version__}[/bold green]\n"
            f"Listening on [cyan]http://{bind_host}:{bind_port}[/cyan]",
            title="SmartQA Server",
        )
    )

    uvicorn.run(
        "smartqa.api:app",
        host=bind_host,
        port=bind_port,
        log_level=settings.log_level.lower(),
    )


# ------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------


def _validate_api_key(settings: Settings) -> None:
    if not settings.claude_api_key:
        console.print(
            "[bold red]Error:[/bold red] CLAUDE_API_KEY is not set. "
            "Export it or add it to your .env file."
        )
        sys.exit(1)


def _render_test_plan(plan: TestPlan) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold]URL:[/bold] {plan.url}\n"
            f"[bold]Tests Generated:[/bold] {plan.total_tests}\n"
            f"[bold]Coverage:[/bold] {plan.coverage_summary}",
            title="[bold cyan]Test Plan[/bold cyan]",
        )
    )

    table = Table(title="Generated Test Cases", show_lines=True)
    table.add_column("#", justify="right", width=4)
    table.add_column("Name", min_width=30)
    table.add_column("Category", width=12)
    table.add_column("Risk", width=10)
    table.add_column("Priority", justify="right", width=10)
    table.add_column("Steps", justify="right", width=6)

    for i, tc in enumerate(plan.test_cases, 1):
        risk_color = {
            RiskLevel.CRITICAL: "red",
            RiskLevel.HIGH: "yellow",
            RiskLevel.MEDIUM: "cyan",
            RiskLevel.LOW: "green",
        }.get(tc.risk_level, "white")

        table.add_row(
            str(i),
            tc.name,
            tc.category.value,
            f"[{risk_color}]{tc.risk_level.value}[/{risk_color}]",
            f"{tc.priority_score:.1f}",
            str(len(tc.steps)),
        )

    console.print(table)
    console.print()


def _render_qa_report(report: QAReport) -> None:
    console.print()

    pass_rate = (
        (report.tests_passed / report.tests_generated * 100)
        if report.tests_generated
        else 0
    )
    risk_color = "green" if report.risk_score < 30 else "yellow" if report.risk_score < 60 else "red"

    console.print(
        Panel(
            f"[bold]Application:[/bold] {report.application_url}\n"
            f"[bold]Tests Generated:[/bold] {report.tests_generated}\n"
            f"[bold green]Passed:[/bold green] {report.tests_passed}\n"
            f"[bold red]Failed:[/bold red] {report.tests_failed}\n"
            f"[bold yellow]Self-Healed:[/bold yellow] {report.self_healed_failures}\n"
            f"[bold]Pass Rate:[/bold] {pass_rate:.1f}%\n"
            f"[bold]Risk Score:[/bold] [{risk_color}]{report.risk_score:.0f}/100[/{risk_color}]",
            title="[bold cyan]QA Report[/bold cyan]",
        )
    )

    if report.execution_report:
        results_table = Table(title="Test Results", show_lines=True)
        results_table.add_column("#", justify="right", width=4)
        results_table.add_column("Test Case", min_width=30)
        results_table.add_column("Status", width=10)
        results_table.add_column("Duration", justify="right", width=10)
        results_table.add_column("Healed", width=8)

        for i, result in enumerate(report.execution_report.test_results, 1):
            status_style = {
                TestStatus.PASSED: "[green]PASS[/green]",
                TestStatus.FAILED: "[red]FAIL[/red]",
                TestStatus.ERROR: "[red]ERROR[/red]",
                TestStatus.SKIPPED: "[dim]SKIP[/dim]",
                TestStatus.HEALED: "[yellow]HEALED[/yellow]",
            }.get(result.status, result.status.value)

            healed = "Yes" if any(sr.healed for sr in result.step_results) else ""
            duration = f"{result.duration_ms:.0f} ms"

            results_table.add_row(
                str(i),
                result.test_case.name,
                status_style,
                duration,
                healed,
            )

        console.print(results_table)

    if report.issues:
        console.print()
        issues_table = Table(title="Issues Found", show_lines=True)
        issues_table.add_column("Severity", width=10)
        issues_table.add_column("Description", min_width=40)
        issues_table.add_column("Screenshot", width=20)

        for issue in report.issues:
            sev_style = {
                Severity.CRITICAL: "[bold red]CRITICAL[/bold red]",
                Severity.HIGH: "[red]HIGH[/red]",
                Severity.MEDIUM: "[yellow]MEDIUM[/yellow]",
                Severity.LOW: "[green]LOW[/green]",
            }.get(issue.severity, issue.severity.value)

            issues_table.add_row(
                sev_style,
                issue.description[:100],
                issue.screenshot_path or "-",
            )

        console.print(issues_table)

    console.print()


def _write_json(data: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    console.print(f"[dim]Report written to {path}[/dim]")
