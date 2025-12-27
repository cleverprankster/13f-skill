"""Configuration management for 13F Skill."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _get_user_agent() -> str:
    """Get User-Agent for SEC EDGAR. SEC requires contact info."""
    email = os.environ.get("SEC_CONTACT_EMAIL", "")
    if not email:
        raise ValueError(
            "SEC_CONTACT_EMAIL environment variable is required. "
            "SEC EDGAR requires a contact email in the User-Agent header. "
            "Set it with: export SEC_CONTACT_EMAIL=your@email.com"
        )
    return f"13F-Skill {email}"


@dataclass
class Config:
    """Application configuration."""

    # Paths - __file__ is config.py in src/thirteen_f/, so .parent.parent.parent = 13f-skill/
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)
    data_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)
    artifacts_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    funds_file: Path = field(init=False)

    # SEC EDGAR settings
    user_agent: str = field(default_factory=_get_user_agent)
    rate_limit_per_second: float = 10.0  # SEC guideline: max 10 requests/second

    # Defaults
    default_periods: int = 5  # latest + 4 prior quarters
    starter_weight_min: float = 0.0001  # 0.01%
    starter_weight_max: float = 0.0025  # 0.25%
    starter_value_threshold: int = 5_000_000  # $5M

    def __post_init__(self) -> None:
        self.data_dir = self.base_dir / "data"
        self.cache_dir = self.data_dir / "cache"
        self.artifacts_dir = self.base_dir / "artifacts"
        self.db_path = self.data_dir / "13f.db"
        self.funds_file = self.data_dir / "funds.yaml"

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class Fund:
    """A fund to track."""

    display_name: str
    cik: str
    tags: list[str] = field(default_factory=list)


def load_funds(config: Config) -> list[Fund]:
    """Load funds from the YAML config file."""
    if not config.funds_file.exists():
        return []

    with open(config.funds_file) as f:
        data = yaml.safe_load(f) or {}

    funds_data = data.get("funds", [])
    return [
        Fund(
            display_name=fd["display_name"],
            cik=fd["cik"],
            tags=fd.get("tags", []),
        )
        for fd in funds_data
    ]


def save_funds(config: Config, funds: list[Fund]) -> None:
    """Save funds to the YAML config file."""
    data = {
        "funds": [
            {
                "display_name": f.display_name,
                "cik": f.cik,
                "tags": f.tags,
            }
            for f in funds
        ]
    }
    with open(config.funds_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_config() -> Config:
    """Get the default configuration."""
    return Config()
