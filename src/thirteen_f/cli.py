"""13F Analysis CLI."""

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import click

from .config import Config, Fund, get_config, load_funds, save_funds


# =============================================================================
# Security Helpers
# =============================================================================


def validate_output_path(output: str, config: Config) -> Path:
    """
    Validate that an output path is safe (no path traversal).

    Args:
        output: User-provided output path
        config: Application config

    Returns:
        Validated absolute Path

    Raises:
        click.ClickException: If path is outside allowed directories
    """
    output_path = Path(output).resolve()

    # Allowed base directories
    allowed_bases = [
        config.base_dir.resolve(),
        config.artifacts_dir.resolve(),
        Path.cwd().resolve(),
        Path.home().resolve(),
    ]

    # Check if path is under any allowed directory
    for base in allowed_bases:
        try:
            output_path.relative_to(base)
            return output_path
        except ValueError:
            continue

    raise click.ClickException(
        f"Output path must be within the project directory, artifacts, "
        f"current directory, or home directory. Got: {output_path}"
    )


def sanitize_fund_name(name: str) -> str:
    """
    Validate and sanitize a fund name.

    Args:
        name: User-provided fund name

    Returns:
        Sanitized name

    Raises:
        click.ClickException: If name contains invalid characters
    """
    if not name or len(name) > 255:
        raise click.ClickException("Fund name must be 1-255 characters")

    # Disallow characters that could break YAML or cause issues
    invalid_chars = [':', '\n', '\r', '\t', '\x00']
    for char in invalid_chars:
        if char in name:
            raise click.ClickException(
                f"Fund name contains invalid character: {repr(char)}"
            )

    return name.strip()


def sanitize_tag(tag: str) -> str:
    """
    Validate and sanitize a tag.

    Args:
        tag: User-provided tag

    Returns:
        Sanitized tag

    Raises:
        click.ClickException: If tag is invalid
    """
    tag = tag.strip()
    if not tag:
        return ""

    if len(tag) > 50:
        raise click.ClickException(f"Tag too long (max 50 chars): {tag[:20]}...")

    # Only allow alphanumeric, hyphens, underscores
    if not re.match(r'^[\w\-]+$', tag):
        raise click.ClickException(
            f"Tag contains invalid characters (only alphanumeric, -, _ allowed): {tag}"
        )

    return tag


def escape_applescript_string(s: str) -> str:
    """Escape a string for safe use in AppleScript.

    AppleScript escapes quotes by doubling them, not with backslash.
    Also escape backslashes for safety.
    """
    return s.replace('\\', '\\\\').replace('"', '" & quote & "')


from .edgar.client import EdgarClient
from .edgar.parser import compute_filing_totals, parse_13f_info_table
from .edgar.submissions import (
    FilingInfo,
    find_info_table_filename,
    get_13f_filings,
    get_latest_filing_period,
    period_to_quarter,
)
from .reports.fund_report import generate_fund_report
from .reports.universe import generate_universe_report
from .storage.database import Database
from .storage.exports import export_to_csv, export_to_parquet
from .storage.models import FilingRecord, FundRecord


def _print_markdown(content: str) -> None:
    """Print markdown content with rich formatting."""
    from rich.console import Console
    from rich.markdown import Markdown
    console = Console()
    console.print(Markdown(content))


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """13F Analysis Tool - Deterministic 13F ingestion and analysis."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = get_config()


@cli.command("add-fund")
@click.option("--name", required=True, help="Display name for the fund")
@click.option("--cik", required=True, help="SEC CIK number")
@click.option("--tags", default="", help="Comma-separated tags")
@click.pass_context
def add_fund(ctx: click.Context, name: str, cik: str, tags: str) -> None:
    """Add a fund to the tracking list."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    # Sanitize inputs
    name = sanitize_fund_name(name)

    # Check if fund already exists
    for f in funds:
        if f.display_name.lower() == name.lower():
            click.echo(f"Fund '{name}' already exists.")
            return

    # Normalize and validate CIK (should be numeric)
    cik_clean = cik.lstrip("0")
    if not cik_clean.isdigit():
        raise click.ClickException("CIK must be numeric")
    cik_normalized = cik_clean.zfill(10)

    # Parse and sanitize tags
    tag_list = []
    if tags:
        for t in tags.split(","):
            sanitized = sanitize_tag(t)
            if sanitized:
                tag_list.append(sanitized)

    fund = Fund(display_name=name, cik=cik_normalized, tags=tag_list)
    funds.append(fund)
    save_funds(config, funds)

    click.echo(f"Added fund: {name} (CIK: {cik_normalized})")


@cli.command("remove-fund")
@click.option("--name", required=True, help="Fund name to remove")
@click.pass_context
def remove_fund(ctx: click.Context, name: str) -> None:
    """Remove a fund from the tracking list."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    original_count = len(funds)
    funds = [f for f in funds if f.display_name.lower() != name.lower()]

    if len(funds) == original_count:
        click.echo(f"Fund '{name}' not found.")
        return

    save_funds(config, funds)

    # Also remove from database
    with Database(config) as db:
        db.delete_fund(name)

    click.echo(f"Removed fund: {name}")


@cli.command("list-funds")
@click.pass_context
def list_funds(ctx: click.Context) -> None:
    """List all tracked funds."""
    from rich.console import Console
    from rich.table import Table

    config = ctx.obj["config"]
    funds = load_funds(config)

    if not funds:
        click.echo("No funds configured. Use 'add-fund' to add funds.")
        return

    console = Console()
    table = Table(title="Tracked Funds")
    table.add_column("Name", style="cyan")
    table.add_column("CIK")
    table.add_column("Tags", style="dim")

    for f in funds:
        tags_str = ", ".join(f.tags) if f.tags else "-"
        table.add_row(f.display_name, f.cik, tags_str)

    console.print(table)


@cli.command("pull")
@click.option("--fund", "fund_name", help="Fund name to pull")
@click.option("--all", "pull_all", is_flag=True, help="Pull all tracked funds and stocks")
@click.option("--periods", default=5, help="Number of periods to pull (default: 5)")
@click.option("--original-only", is_flag=True, help="Ignore amendments")
@click.option("--skip-stocks", is_flag=True, help="Skip updating tracked stocks (with --all)")
@click.pass_context
def pull(
    ctx: click.Context,
    fund_name: str | None,
    pull_all: bool,
    periods: int,
    original_only: bool,
    skip_stocks: bool,
) -> None:
    """Pull 13F filings from SEC EDGAR."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    if not funds:
        click.echo("No funds configured. Use 'add-fund' to add funds.")
        return

    if not fund_name and not pull_all:
        click.echo("Specify --fund or --all")
        return

    # Filter funds
    if pull_all:
        target_funds = funds
    else:
        target_funds = [f for f in funds if f.display_name.lower() == fund_name.lower()]
        if not target_funds:
            click.echo(f"Fund '{fund_name}' not found.")
            return

    # Create run artifact directory
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifact_dir = config.artifacts_dir / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with EdgarClient(config) as client, Database(config) as db:
        for fund in target_funds:
            click.echo(f"\nPulling filings for {fund.display_name}...")

            # Ensure fund is in database
            fund_record = FundRecord(
                id=None,
                display_name=fund.display_name,
                cik=fund.cik,
                tags=fund.tags,
            )
            fund_id = db.upsert_fund(fund_record)

            try:
                filings = get_13f_filings(
                    client, fund.cik, periods=periods, original_only=original_only
                )
            except Exception as e:
                click.echo(f"  Error fetching filings: {e}")
                continue

            if not filings:
                click.echo(f"  No 13F filings found for CIK {fund.cik}")
                continue

            click.echo(f"  Found {len(filings)} filing(s)")

            for filing_info in filings:
                quarter = period_to_quarter(filing_info.period_of_report)

                # Check if already ingested
                if db.filing_exists(filing_info.accession_number):
                    click.echo(f"  {quarter}: Already ingested, skipping")
                    continue

                click.echo(f"  {quarter}: Processing {filing_info.accession_number}...")

                # Find info table file
                info_table_file = find_info_table_filename(
                    client, fund.cik, filing_info.accession_number
                )
                if not info_table_file:
                    click.echo(f"    Warning: Could not find info table file")
                    continue

                # Fetch and parse info table
                try:
                    xml_content = client.get_info_table_xml(
                        fund.cik, filing_info.accession_number, info_table_file
                    )
                    holdings = parse_13f_info_table(xml_content)
                except Exception as e:
                    click.echo(f"    Error parsing info table: {e}")
                    continue

                if not holdings:
                    click.echo(f"    Warning: No holdings parsed")
                    continue

                total_value, position_count = compute_filing_totals(holdings)

                # Store filing
                filing_record = FilingRecord(
                    id=None,
                    fund_id=fund_id,
                    accession_number=filing_info.accession_number,
                    form_type=filing_info.form_type,
                    filing_date=filing_info.filing_date,
                    period_of_report=filing_info.period_of_report,
                    is_amendment=filing_info.is_amendment,
                    total_value_usd=total_value,
                    position_count=position_count,
                )
                filing_id = db.upsert_filing(filing_record)

                # Store holdings
                inserted = db.insert_holdings(filing_id, holdings)
                click.echo(f"    Stored {inserted} holdings (${total_value:,})")

                # Export to artifacts
                filing_record.id = filing_id
                fund_artifact_dir = artifact_dir / fund.display_name.replace(" ", "_")
                export_to_csv(db, filing_record, fund_artifact_dir)
                export_to_parquet(db, filing_record, fund_artifact_dir)

    click.echo(f"\nArtifacts saved to: {artifact_dir}")

    # Update tracked stocks if --all and not --skip-stocks
    if pull_all and not skip_stocks:
        _update_tracked_stocks(config)


@cli.command("report")
@click.option("--fund", "fund_name", required=True, help="Fund name")
@click.option("--period", default="latest", help="Period (e.g., '2025-09-30' or 'latest')")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def report(ctx: click.Context, fund_name: str, period: str, output: str | None) -> None:
    """Generate analysis report for a fund."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    # Find fund
    fund = next((f for f in funds if f.display_name.lower() == fund_name.lower()), None)
    if not fund:
        click.echo(f"Fund '{fund_name}' not found.")
        return

    with Database(config) as db:
        fund_record = db.get_fund_by_name(fund.display_name)
        if not fund_record:
            click.echo(f"No data for fund '{fund_name}'. Run 'pull' first.")
            return

        period_date = None if period == "latest" else period
        report_md = generate_fund_report(
            db, fund_record.id, fund_record.display_name, config, period_date
        )

    if output:
        output_path = validate_output_path(output, config)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_md)
        click.echo(f"Report saved to: {output_path}")
    else:
        _print_markdown(report_md)


@cli.command("compare")
@click.option("--fund", "fund_name", required=True, help="Fund name")
@click.option("--from", "from_period", required=True, help="Start period (e.g., '2025Q2')")
@click.option("--to", "to_period", required=True, help="End period (e.g., '2025Q3')")
@click.pass_context
def compare(ctx: click.Context, fund_name: str, from_period: str, to_period: str) -> None:
    """Compare two periods for a fund."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    fund = next((f for f in funds if f.display_name.lower() == fund_name.lower()), None)
    if not fund:
        click.echo(f"Fund '{fund_name}' not found.")
        return

    from .analysis.diff import compute_quarter_diff
    from .edgar.submissions import quarter_to_period

    with Database(config) as db:
        fund_record = db.get_fund_by_name(fund.display_name)
        if not fund_record:
            click.echo(f"No data for fund '{fund_name}'. Run 'pull' first.")
            return

        # Convert quarters to dates
        try:
            period_from = quarter_to_period(from_period)
            period_to = quarter_to_period(to_period)
        except ValueError as e:
            click.echo(f"Invalid period format: {e}")
            return

        filing_from = db.get_filing_by_period(fund_record.id, period_from)
        filing_to = db.get_filing_by_period(fund_record.id, period_to)

        if not filing_from:
            click.echo(f"No filing found for period {from_period}")
            return
        if not filing_to:
            click.echo(f"No filing found for period {to_period}")
            return

        diff = compute_quarter_diff(
            db, fund_record.id, fund_record.display_name, filing_from, filing_to, config
        )

        click.echo(diff.to_json())


@cli.command("universe-report")
@click.option("--funds", required=True, help="Comma-separated fund names")
@click.option("--period", default="latest", help="Period (default: latest)")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def universe_report(
    ctx: click.Context, funds: str, period: str, output: str | None
) -> None:
    """Generate cross-fund comparison report."""
    config = ctx.obj["config"]
    all_funds = load_funds(config)

    # Parse fund names
    fund_names_input = [f.strip() for f in funds.split(",")]

    # Find matching funds
    matched_funds = []
    for name in fund_names_input:
        fund = next(
            (f for f in all_funds if f.display_name.lower() == name.lower()), None
        )
        if fund:
            matched_funds.append(fund)
        else:
            click.echo(f"Warning: Fund '{name}' not found, skipping")

    if not matched_funds:
        click.echo("No valid funds found.")
        return

    with Database(config) as db:
        fund_ids = []
        fund_names = []
        for fund in matched_funds:
            fund_record = db.get_fund_by_name(fund.display_name)
            if fund_record:
                fund_ids.append(fund_record.id)
                fund_names.append(fund_record.display_name)
            else:
                click.echo(f"Warning: No data for '{fund.display_name}', skipping")

        if not fund_ids:
            click.echo("No fund data available. Run 'pull' first.")
            return

        report_md = generate_universe_report(db, fund_ids, fund_names, config)

    if output:
        output_path = validate_output_path(output, config)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_md)
        click.echo(f"Report saved to: {output_path}")
    else:
        _print_markdown(report_md)


@cli.command("lookup-cik")
@click.option("--name", required=True, help="Company name to search")
@click.pass_context
def lookup_cik(ctx: click.Context, name: str) -> None:
    """Look up CIK by company name (best-effort)."""
    config = ctx.obj["config"]

    click.echo(f"Searching for '{name}'...")
    click.echo(
        "Note: This is a best-effort search. Please verify CIKs on SEC EDGAR directly."
    )
    click.echo(f"https://www.sec.gov/cgi-bin/browse-edgar?company={name.replace(' ', '+')}&CIK=&type=13F&owner=include&count=40&action=getcompany")


@cli.command("export")
@click.option("--fund", "fund_name", required=True, help="Fund name")
@click.option("--format", "fmt", type=click.Choice(["csv", "parquet"]), default="csv")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.pass_context
def export(ctx: click.Context, fund_name: str, fmt: str, output: str | None) -> None:
    """Export fund data to CSV or Parquet."""
    config = ctx.obj["config"]
    funds = load_funds(config)

    fund = next((f for f in funds if f.display_name.lower() == fund_name.lower()), None)
    if not fund:
        click.echo(f"Fund '{fund_name}' not found.")
        return

    if output:
        output_path = validate_output_path(output, config)
    else:
        output_path = config.artifacts_dir / "exports"
    output_path.mkdir(parents=True, exist_ok=True)

    with Database(config) as db:
        fund_record = db.get_fund_by_name(fund.display_name)
        if not fund_record:
            click.echo(f"No data for fund '{fund_name}'. Run 'pull' first.")
            return

        filings = db.get_filings_for_fund(fund_record.id)
        for filing in filings:
            if fmt == "csv":
                path = export_to_csv(db, filing, output_path)
            else:
                path = export_to_parquet(db, filing, output_path)
            click.echo(f"Exported: {path}")


def _send_notification(title: str, message: str) -> None:
    """Send macOS notification."""
    import subprocess

    # Escape strings to prevent AppleScript injection
    safe_title = escape_applescript_string(title)
    safe_message = escape_applescript_string(message)

    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe_message}" with title "{safe_title}"',
        ],
        capture_output=True,
    )


def _update_tracked_stocks(config: Config) -> None:
    """Update data for all tracked stocks."""
    from .sec.quarterly_data import extract_cusip_holdings, get_available_quarters
    from .storage.stock_storage import (
        load_tracked_stocks,
        save_stock_holdings,
        get_stock_quarters,
    )

    stocks = load_tracked_stocks(config)
    if not stocks:
        return

    click.echo(f"\nUpdating {len(stocks)} tracked stock(s)...")

    # Get available quarters
    quarters = get_available_quarters()[:4]
    if not quarters:
        click.echo("  No quarterly data available.")
        return

    for stock in stocks:
        click.echo(f"  {stock.ticker}:", nl=False)

        # Find quarters we don't have yet
        existing_quarters = set(get_stock_quarters(stock.ticker, config))
        new_quarters = [q for q in quarters if q not in existing_quarters]

        if not new_quarters:
            click.echo(" Up to date")
            continue

        for quarter in new_quarters:
            try:
                holdings = extract_cusip_holdings(quarter, stock.cusip, config, min_value=50_000_000)
                save_stock_holdings(stock.ticker, quarter, holdings, config)
                click.echo(f" {quarter}({len(holdings)})", nl=False)
            except Exception as e:
                click.echo(f" {quarter}(err)", nl=False)

        click.echo("")

    click.echo("Stock updates complete.")


@cli.command("check-new")
@click.option("--pull", "auto_pull", is_flag=True, help="Auto-pull new filings")
@click.option("--notify", "send_notify", is_flag=True, help="Send macOS notification")
@click.pass_context
def check_new(ctx: click.Context, auto_pull: bool, send_notify: bool) -> None:
    """Check for new 13F filings not yet in database."""
    from rich.console import Console
    from rich.table import Table

    config = ctx.obj["config"]
    funds = load_funds(config)

    if not funds:
        click.echo("No funds configured. Use 'add-fund' to add funds.")
        return

    click.echo("Checking for new filings...\n")

    console = Console()
    table = Table(title="13F Filing Status")
    table.add_column("Fund", style="cyan")
    table.add_column("Latest in DB")
    table.add_column("SEC Latest")
    table.add_column("Status")

    funds_with_new = []
    rows = []

    with EdgarClient(config) as client, Database(config) as db:
        for fund in funds:
            fund_record = db.get_fund_by_name(fund.display_name)

            # Get latest from database
            db_latest = "-"
            if fund_record:
                latest_filing = db.get_latest_filing_for_fund(fund_record.id)
                if latest_filing:
                    db_latest = latest_filing.period_of_report

            # Get latest from SEC (bypass cache)
            try:
                sec_latest = get_latest_filing_period(client, fund.cik)
                if not sec_latest:
                    sec_latest = "-"
            except Exception as e:
                sec_latest = f"Error: {e}"

            # Determine status
            if sec_latest == "-" or sec_latest.startswith("Error"):
                status = sec_latest if sec_latest.startswith("Error") else "No filings"
                status_styled = f"[dim]{status}[/dim]"
            elif db_latest == "-":
                status = "NEW"
                status_styled = "[bold green]NEW[/bold green]"
                funds_with_new.append(fund)
            elif sec_latest > db_latest:
                status = "NEW"
                status_styled = "[bold green]NEW[/bold green]"
                funds_with_new.append(fund)
            else:
                status = "Up to date"
                status_styled = "[dim]Up to date[/dim]"

            rows.append((fund.display_name, db_latest, sec_latest, status_styled))

    for row in rows:
        table.add_row(*row)

    console.print(table)

    click.echo("")

    if funds_with_new:
        click.echo(f"{len(funds_with_new)} fund(s) have new filings available.")

        if auto_pull:
            click.echo("\nPulling new filings...")
            # Invoke pull for each fund with new filings
            for fund in funds_with_new:
                ctx.invoke(pull, fund_name=fund.display_name, pull_all=False, periods=1, original_only=False)

            if send_notify:
                fund_names = ", ".join(f.display_name for f in funds_with_new)
                _send_notification(
                    "13F Update",
                    f"Pulled new filings for: {fund_names}",
                )
        else:
            click.echo("Run `13f check-new --pull` to fetch them.")
    else:
        click.echo("All funds are up to date.")

        if send_notify:
            _send_notification("13F Check", "No new filings available.")


@cli.command("calendar")
def calendar() -> None:
    """Show 13F filing calendar and expected dates."""
    from datetime import date

    today = date.today()
    year = today.year

    # Quarter end dates and filing deadlines
    quarters = [
        (f"Q4 {year - 1}", date(year - 1, 12, 31), date(year, 2, 14)),
        (f"Q1 {year}", date(year, 3, 31), date(year, 5, 15)),
        (f"Q2 {year}", date(year, 6, 30), date(year, 8, 14)),
        (f"Q3 {year}", date(year, 9, 30), date(year, 11, 14)),
        (f"Q4 {year}", date(year, 12, 31), date(year + 1, 2, 14)),
    ]

    click.echo(f"\n13F Filing Calendar ({year})")
    click.echo("-" * 50)

    for quarter, period_end, deadline in quarters:
        # Check if we're in the filing window (after quarter end, before/at deadline)
        in_window = period_end < today <= deadline
        current_marker = " ← CURRENT WINDOW" if in_window else ""

        # Check if past deadline
        if today > deadline:
            status = "(filed)"
        elif today <= period_end:
            status = "(upcoming)"
        else:
            days_left = (deadline - today).days
            status = f"({days_left} days left)"

        click.echo(f"{quarter} filings: due {deadline.strftime('%b %d, %Y')} {status}{current_marker}")

    click.echo("")
    click.echo("Most funds file 40-45 days after quarter end.")
    click.echo("")


@cli.command("schedule")
@click.option("--enable", is_flag=True, help="Enable automatic daily checks")
@click.option("--disable", is_flag=True, help="Disable automatic checks")
@click.option("--status", "show_status", is_flag=True, help="Show current schedule status")
@click.option("--hour", default=9, type=click.IntRange(0, 23), help="Hour to run (0-23, default 9)")
@click.option("--minute", default=0, type=click.IntRange(0, 59), help="Minute to run (0-59, default 0)")
def schedule(enable: bool, disable: bool, show_status: bool, hour: int, minute: int) -> None:
    """Manage automatic 13F filing checks (macOS launchd)."""
    from .scheduler import disable_schedule, enable_schedule, get_status

    if sum([enable, disable, show_status]) > 1:
        click.echo("Specify only one of --enable, --disable, or --status")
        return

    if not any([enable, disable, show_status]):
        show_status = True

    if enable:
        success, message = enable_schedule(hour, minute)
        if success:
            click.echo(f"Enabled: {message}")
            click.echo(f"Log file: data/schedule.log")
        else:
            click.echo(f"Error: {message}")

    elif disable:
        success, message = disable_schedule()
        if success:
            click.echo(f"Disabled: {message}")
        else:
            click.echo(f"Error: {message}")

    else:
        status = get_status()
        click.echo("\n13F Schedule Status")
        click.echo("-" * 30)
        click.echo(f"Enabled:    {'Yes' if status.enabled else 'No'}")
        click.echo(f"Plist:      {'Exists' if status.plist_exists else 'Not found'}")
        if status.last_run:
            click.echo(f"Last run:   {status.last_run}")
        if status.next_run:
            click.echo(f"Next run:   {status.next_run}")
        click.echo("")

        if not status.enabled:
            click.echo("Run `13f schedule --enable` to enable daily checks.")


# ============================================================================
# Stock Commands
# ============================================================================


@cli.command("stock")
@click.argument("query")
@click.option("--history", is_flag=True, help="Show quarterly history")
@click.option("--no-exclude-passive", is_flag=True, help="Include passive funds")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.pass_context
def stock(
    ctx: click.Context,
    query: str,
    history: bool,
    no_exclude_passive: bool,
    output: str | None,
    yes: bool,
) -> None:
    """Look up institutional holders of a stock.

    QUERY can be a ticker (TSM), CUSIP (874039100), or company name.

    Examples:
        13f stock TSM
        13f stock TSM --history
        13f stock "Taiwan Semiconductor"
    """
    from .reports.stock_report import generate_stock_report, generate_stock_history_report
    from .sec.cusip_lookup import resolve_ticker_or_cusip, search_issuer_in_quarterly_data, save_cusip_mapping
    from .sec.quarterly_data import extract_cusip_holdings, get_available_quarters
    from .storage.stock_storage import (
        add_tracked_stock,
        get_stock_storage_bytes,
        get_tracked_stock,
        load_stock_holdings,
        save_stock_holdings,
        format_bytes,
        get_stock_quarters,
    )

    config = ctx.obj["config"]

    # Resolve query to CUSIP
    result = resolve_ticker_or_cusip(query, config)

    if not result:
        # Try searching in quarterly data
        click.echo(f"'{query}' not found in known mappings. Searching SEC data...")
        quarters = get_available_quarters()
        if quarters:
            matches = search_issuer_in_quarterly_data(query, quarters[0], config, limit=5)
            if matches:
                click.echo("\nPossible matches:")
                for m in matches:
                    click.echo(f"  {m['cusip']} - {m['issuer_name']} (${m['max_value']:,.0f})")
                click.echo("\nUse the CUSIP directly: 13f stock <CUSIP>")
            else:
                click.echo("No matches found in SEC data.")
        return

    cusip, issuer_name = result
    ticker = query.upper() if len(query) <= 6 else cusip[:6]

    # Check if already tracked
    tracked = get_tracked_stock(ticker, config)

    if not tracked:
        # Estimate storage
        from .sec.quarterly_data import estimate_storage_for_cusip
        est_bytes = estimate_storage_for_cusip(cusip)

        click.echo(f"\n{issuer_name} ({ticker}) is not currently tracked.")
        click.echo(f"This will download ~{format_bytes(est_bytes)} of data (4 quarters).")

        if not yes:
            if not click.confirm("Add to tracked stocks?", default=True):
                click.echo("Aborted.")
                return

        # Add to tracked stocks
        try:
            tracked = add_tracked_stock(ticker, cusip, issuer_name, config)
            click.echo(f"Added {ticker} to tracked stocks.\n")
        except ValueError as e:
            click.echo(f"Error: {e}")
            return

        # Save the cusip mapping for future use
        save_cusip_mapping(config, ticker, cusip, issuer_name)

        # Download data for all available quarters
        click.echo("Downloading quarterly data...")
        quarters = get_available_quarters()[:4]  # Last 4 quarters

        for quarter in quarters:
            click.echo(f"  {quarter}...", nl=False)
            try:
                holdings = extract_cusip_holdings(quarter, cusip, config, min_value=50_000_000)
                save_stock_holdings(ticker, quarter, holdings, config)
                click.echo(f" {len(holdings)} holders")
            except Exception as e:
                click.echo(f" Error: {e}")

        click.echo("")

    # Generate report
    exclude_passive = not no_exclude_passive

    # Get available quarters
    quarters = get_stock_quarters(ticker, config)
    if not quarters:
        click.echo("No data available. Try running 13f pull --all to update.")
        return

    if history:
        report_md = generate_stock_history_report(
            ticker, cusip, issuer_name, config, exclude_passive
        )
    else:
        # Get latest quarter's data
        holdings = load_stock_holdings(ticker, quarters[0], config)
        if not holdings:
            click.echo("No holdings data found.")
            return

        report_md = generate_stock_report(
            ticker, cusip, issuer_name, holdings, config, exclude_passive
        )

    if output:
        output_path = validate_output_path(output, config)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_md)
        click.echo(f"Report saved to: {output_path}")
    else:
        _print_markdown(report_md)


@cli.command("list-stocks")
@click.pass_context
def list_stocks(ctx: click.Context) -> None:
    """List all tracked stocks."""
    from rich.console import Console
    from rich.table import Table

    from .storage.stock_storage import (
        load_tracked_stocks,
        get_stock_storage_bytes,
        get_total_stock_storage,
        format_bytes,
    )

    config = ctx.obj["config"]
    stocks = load_tracked_stocks(config)

    if not stocks:
        click.echo("No stocks tracked. Use '13f stock <ticker>' to add one.")
        return

    storage_info = get_total_stock_storage(config)

    console = Console()
    table = Table(title=f"Tracked Stocks ({len(stocks)} total, {format_bytes(storage_info['total_bytes'])})")
    table.add_column("Ticker", style="cyan")
    table.add_column("Name")
    table.add_column("Quarters", justify="right")
    table.add_column("Holders", justify="right")
    table.add_column("Storage", justify="right")
    table.add_column("Added", style="dim")

    for stock in sorted(stocks, key=lambda s: s.ticker):
        storage = get_stock_storage_bytes(stock.ticker, config)
        added_date = stock.added_at[:10] if stock.added_at else "-"
        table.add_row(
            stock.ticker,
            stock.name[:34],
            str(stock.quarters_stored),
            str(stock.total_holders),
            format_bytes(storage),
            added_date,
        )

    console.print(table)


@cli.command("add-stock")
@click.argument("ticker")
@click.option("--cusip", help="CUSIP (if known)")
@click.option("--name", help="Issuer name (if known)")
@click.pass_context
def add_stock_cmd(ctx: click.Context, ticker: str, cusip: str | None, name: str | None) -> None:
    """Add a stock to tracking without querying.

    Useful for adding stocks with known CUSIPs.
    """
    from .sec.cusip_lookup import resolve_ticker_or_cusip, save_cusip_mapping
    from .sec.quarterly_data import extract_cusip_holdings, get_available_quarters
    from .storage.stock_storage import (
        add_tracked_stock,
        get_tracked_stock,
        save_stock_holdings,
        format_bytes,
    )

    config = ctx.obj["config"]
    ticker = ticker.upper()

    # Check if already tracked
    if get_tracked_stock(ticker, config):
        click.echo(f"{ticker} is already being tracked.")
        return

    # Resolve CUSIP if not provided
    if not cusip:
        result = resolve_ticker_or_cusip(ticker, config)
        if not result:
            click.echo(f"Could not find CUSIP for {ticker}. Use --cusip to specify.")
            return
        cusip, resolved_name = result
        name = name or resolved_name
    else:
        name = name or "Unknown Issuer"

    # Add to tracked stocks
    try:
        add_tracked_stock(ticker, cusip, name, config)
        save_cusip_mapping(config, ticker, cusip, name)
        click.echo(f"Added {ticker} ({name}) to tracked stocks.")
    except ValueError as e:
        click.echo(f"Error: {e}")
        return

    # Download data
    click.echo("Downloading quarterly data...")
    quarters = get_available_quarters()[:4]

    for quarter in quarters:
        click.echo(f"  {quarter}...", nl=False)
        try:
            holdings = extract_cusip_holdings(quarter, cusip, config, min_value=50_000_000)
            save_stock_holdings(ticker, quarter, holdings, config)
            click.echo(f" {len(holdings)} holders")
        except Exception as e:
            click.echo(f" Error: {e}")

    click.echo(f"\n{ticker} is now being tracked.")


@cli.command("remove-stock")
@click.argument("ticker")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def remove_stock_cmd(ctx: click.Context, ticker: str, yes: bool) -> None:
    """Remove a stock from tracking and delete its data."""
    from .storage.stock_storage import (
        get_tracked_stock,
        get_stock_storage_bytes,
        remove_tracked_stock,
        format_bytes,
    )

    config = ctx.obj["config"]
    ticker = ticker.upper()

    # Check if tracked
    stock = get_tracked_stock(ticker, config)
    if not stock:
        click.echo(f"{ticker} is not being tracked.")
        return

    # Show storage info
    storage = get_stock_storage_bytes(ticker, config)
    click.echo(f"\n{stock.name} ({ticker})")
    click.echo(f"Removing will free up {format_bytes(storage)} of data.")

    if not yes:
        if not click.confirm("Remove from tracked stocks?", default=False):
            click.echo("Aborted.")
            return

    # Remove
    try:
        bytes_freed = remove_tracked_stock(ticker, config)
        click.echo(f"\n{ticker} removed. {format_bytes(bytes_freed)} freed.")
    except ValueError as e:
        click.echo(f"Error: {e}")


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
