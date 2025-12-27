# 13F Analysis Skill

Deterministic 13F ingestion and analysis tool for tracking hedge fund holdings.

## What is a 13F?

A **13F filing** is a quarterly report that institutional investment managers with over $100M in assets must file with the SEC. It discloses their equity holdings, giving insight into what major hedge funds are buying and selling.

This tool lets you:
- Track specific funds and pull their 13F filings automatically
- Analyze portfolio changes quarter-over-quarter
- Identify thesis signals (consistent accumulation, build-then-trim patterns, new probes)
- Compare holdings across multiple funds
- Look up who owns any stock

## Setup

### 1. Install the CLI

```bash
git clone https://github.com/cleverprankster/13f-skill.git
cd 13f-skill
pip install -e .
```

### 2. Set your SEC contact email (required)

SEC EDGAR requires a contact email in the User-Agent header:

```bash
# Add to your ~/.zshrc or ~/.bashrc
export SEC_CONTACT_EMAIL=your@email.com
```

### 3. Verify installation

```bash
# Check CLI is installed
13f --version

# List pre-configured funds
13f list-funds
```

### 4. Install the Claude Code skill (optional)

To use natural language commands with Claude Code:

```bash
cp .claude/commands/13f.md ~/.claude/commands/
```

## Quick Start

```bash
# List pre-configured funds
13f list-funds

# Pull latest filings for all funds
13f pull --all

# Generate analysis report
13f report --fund "Coatue Management"

# Cross-fund comparison
13f universe-report --funds "Coatue Management,Altimeter Capital"

# Check for new filings
13f check-new

# Look up who owns a stock
13f stock NVDA
```

## Claude Code Integration

With the skill installed, use natural language:

```
/13f analyze Tiger Global
/13f who owns NVDA?
/13f compare Coatue and Altimeter
/13f check for new filings and pull them
/13f show me Coatue's top positions
```

Or use CLI syntax directly:

```
/13f report --fund "Tiger Global"
/13f stock TSM --history
/13f universe-report --funds "Coatue,Altimeter,Tiger Global"
```

## Commands

### Fund Management

| Command | Description |
|---------|-------------|
| `list-funds` | List all tracked funds |
| `add-fund` | Add a fund to track |
| `remove-fund` | Remove a fund |
| `lookup-cik` | Look up a fund's CIK by name |

### Data Fetching

| Command | Description |
|---------|-------------|
| `pull` | Fetch 13F filings from SEC EDGAR |
| `check-new` | Check for new filings not yet downloaded |
| `calendar` | Show 13F filing deadlines |
| `schedule` | Set up automatic daily checks (macOS) |

### Analysis & Reports

| Command | Description |
|---------|-------------|
| `report` | Generate analysis report for a fund |
| `compare` | Compare two specific quarters |
| `universe-report` | Cross-fund comparison report |
| `export` | Export data to CSV/Parquet |

### Stock Tracking

| Command | Description |
|---------|-------------|
| `stock` | Look up institutional holders of a stock |
| `list-stocks` | List all tracked stocks |
| `add-stock` | Add a stock to tracking |
| `remove-stock` | Remove a stock from tracking |

## Pre-configured Funds

The following funds are included by default and ready to use after installation:

| Fund | CIK | Tags |
|------|-----|------|
| Coatue Management | 0001135730 | tiger-cub, tech |
| Altimeter Capital | 0001541617 | tech, growth |
| Appaloosa Management | 0001656456 | macro, distressed |
| Tiger Global | 0001167483 | tiger-cub, tech |
| Strategy Capital | 0001592413 | tech |
| Atreides Management | 0001777813 | tiger-cub, tech |

Add more funds with `13f add-fund --name "Fund Name" --cik "0001234567"`

## Command Examples

### Pulling Data

```bash
# Pull all funds and update tracked stocks
13f pull --all

# Pull specific fund
13f pull --fund "Tiger Global"

# Pull more history (default is 5 quarters)
13f pull --all --periods 10
```

### Generating Reports

```bash
# Latest quarter report
13f report --fund "Coatue Management"

# Save to file
13f report --fund "Coatue Management" -o coatue-q3.md

# Compare two quarters
13f compare --fund "Coatue Management" --from 2025Q2 --to 2025Q3
```

### Cross-Fund Analysis

```bash
# Compare multiple funds
13f universe-report --funds "Coatue Management,Altimeter Capital,Tiger Global"

# Find overlapping holdings, divergent bets, shared moves
```

### Stock Lookup

```bash
# Who owns NVIDIA?
13f stock NVDA

# Show quarterly history
13f stock NVDA --history

# Search by CUSIP
13f stock 67066G104

# Include passive funds (normally excluded)
13f stock NVDA --no-exclude-passive
```

### Checking for Updates

```bash
# See what's new on SEC EDGAR
13f check-new

# Auto-pull any new filings
13f check-new --pull

# With macOS notification
13f check-new --pull --notify
```

### Scheduling (macOS)

```bash
# Enable daily checks at 9am
13f schedule --enable

# Check at different time
13f schedule --enable --hour 8

# View status
13f schedule --status

# Disable
13f schedule --disable
```

### Adding New Funds

```bash
# Look up CIK
13f lookup-cik --name "Pershing Square"

# Add to tracking
13f add-fund --name "Pershing Square" --cik "0001336528" --tags "activist"

# Pull their data
13f pull --fund "Pershing Square"
```

## Analysis Features

### Report Contents
- **Portfolio Map:** Top 10 holdings, cluster breakdown, small positions
- **Changes:** Ranked by $ value, growth rate, and portfolio impact
- **Thesis Signals:** Consistent accumulator, build-then-trim, probes
- **Year-to-Date:** Starter→scale positions, net new/exited names

### Thesis Signals

| Signal | Description |
|--------|-------------|
| 🔴 Consistent Accumulator | Increased position 4+ consecutive quarters |
| 🟡 Consistent Accumulator | Increased position 3 consecutive quarters |
| 🟡 Build Then Trim | Built for 2+ quarters, then trimmed |
| ⚪ One Quarter Probe | Opened and closed within 2-3 quarters |

### Starter Detection

Positions flagged as "starters" (early conviction bets) if:
- Weight between 0.01% and 0.25%, OR
- Value below $5M

## Data Storage

```
13f-skill/
├── data/
│   ├── funds.yaml              # Tracked fund list
│   ├── tracked_stocks.yaml     # Tracked stock list
│   ├── passive_funds.yaml      # Funds to exclude from stock reports
│   ├── cusip_mappings.json     # User-added ticker→CUSIP mappings
│   ├── cache/                  # Raw SEC responses
│   ├── stock_holdings/         # Stock holder data by quarter
│   └── 13f.db                  # SQLite database
└── artifacts/                  # Generated reports and exports
```

## Architecture

```
src/thirteen_f/
├── cli.py              # Click CLI entry point
├── config.py           # Configuration management
├── scheduler.py        # macOS launchd scheduling
├── edgar/
│   ├── client.py       # SEC EDGAR HTTP client
│   ├── submissions.py  # Filing discovery
│   └── parser.py       # 13F XML parser
├── sec/
│   ├── cusip_lookup.py # CUSIP→ticker resolution
│   └── quarterly_data.py # Stock holder data fetching
├── storage/
│   ├── database.py     # SQLite storage
│   ├── models.py       # Data models
│   ├── exports.py      # CSV/Parquet export
│   └── stock_storage.py # Stock holder storage
├── analysis/
│   ├── diff.py         # Quarter-over-quarter diff
│   ├── signals.py      # Thesis signal detection
│   └── clustering.py   # Sector clustering
└── reports/
    ├── fund_report.py  # Single fund report
    ├── stock_report.py # Stock holder report
    └── universe.py     # Cross-fund comparison
```

## SEC EDGAR Compliance

- **User-Agent:** `13F-Skill <your SEC_CONTACT_EMAIL>`
- **Rate limit:** 10 requests/second (SEC guideline)
- **Caching:** Raw responses cached to avoid redundant downloads

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/
```

## Troubleshooting

### SEC_CONTACT_EMAIL not set

```
Error: SEC_CONTACT_EMAIL environment variable is required.
```

**Fix:** Add to your shell config:
```bash
echo 'export SEC_CONTACT_EMAIL=your@email.com' >> ~/.zshrc
source ~/.zshrc
```

### No funds configured

```
No funds configured. Use 'add-fund' to add funds.
```

**Fix:** The pre-configured funds should auto-install on first run. If not, reinstall:
```bash
pip install -e .
```

### Rate limiting from SEC EDGAR

SEC limits requests to 10/second. The CLI respects this, but if you see rate limit errors:
- Wait a few minutes before retrying
- Avoid running multiple pulls simultaneously

### Command not found: 13f

**Fix:** Ensure the package is installed in your active Python environment:
```bash
pip install -e .
```

If using a virtual environment, make sure it's activated.

## Command Patterns

> **Note:** Some commands use positional arguments, others use named options:
> - `13f stock NVDA` — positional (ticker as argument)
> - `13f report --fund "Coatue"` — named option
>
> When in doubt, use `13f <command> --help` to see the expected format.

## License

MIT
