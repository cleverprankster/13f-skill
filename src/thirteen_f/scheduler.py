"""macOS launchd scheduler for automatic 13F filing checks."""

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PLIST_NAME = "com.13f-skill.check"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_NAME}.plist"


@dataclass
class ScheduleStatus:
    """Status of the scheduled job."""

    enabled: bool
    plist_exists: bool
    last_run: str | None
    next_run: str | None


def get_13f_executable() -> str:
    """Find the 13f CLI executable path."""
    # Try to find it in the PATH
    result = subprocess.run(
        ["which", "13f"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    # Fallback to python -m
    return f"{sys.executable} -m thirteen_f.cli"


def create_plist(hour: int = 9, minute: int = 0) -> str:
    """
    Generate the launchd plist content.

    Args:
        hour: Hour to run (24-hour format, default 9)
        minute: Minute to run (default 0)

    Returns:
        Plist XML content
    """
    executable = get_13f_executable()
    log_path = Path(__file__).parent.parent.parent / "data" / "schedule.log"

    # If using python -m, we need to split the command
    if executable.startswith(sys.executable):
        program_args = f"""    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>thirteen_f.cli</string>
        <string>check-new</string>
        <string>--pull</string>
        <string>--notify</string>
    </array>"""
    else:
        program_args = f"""    <array>
        <string>{executable}</string>
        <string>check-new</string>
        <string>--pull</string>
        <string>--notify</string>
    </array>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
{program_args}
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>WorkingDirectory</key>
    <string>{Path(__file__).parent.parent.parent}</string>
</dict>
</plist>
"""


def enable_schedule(hour: int = 9, minute: int = 0) -> tuple[bool, str]:
    """
    Enable the scheduled 13F check.

    Args:
        hour: Hour to run (24-hour format, default 9)
        minute: Minute to run (default 0)

    Returns:
        Tuple of (success, message)
    """
    # Create LaunchAgents directory if needed
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Unload if already loaded
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
    )

    # Write plist
    plist_content = create_plist(hour, minute)
    PLIST_PATH.write_text(plist_content)

    # Load the job
    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to load: {result.stderr}"

    return True, f"Scheduled daily check at {hour:02d}:{minute:02d}"


def disable_schedule() -> tuple[bool, str]:
    """
    Disable the scheduled 13F check.

    Returns:
        Tuple of (success, message)
    """
    if not PLIST_PATH.exists():
        return False, "Schedule not configured"

    # Unload the job
    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )

    # Remove the plist file
    PLIST_PATH.unlink(missing_ok=True)

    if result.returncode != 0:
        return True, f"Plist removed (was not loaded)"

    return True, "Schedule disabled"


def get_status() -> ScheduleStatus:
    """
    Get the current schedule status.

    Returns:
        ScheduleStatus object
    """
    plist_exists = PLIST_PATH.exists()

    # Check if loaded
    result = subprocess.run(
        ["launchctl", "list", PLIST_NAME],
        capture_output=True,
        text=True,
    )
    enabled = result.returncode == 0

    # Get last run from log file
    log_path = Path(__file__).parent.parent.parent / "data" / "schedule.log"
    last_run = None
    if log_path.exists():
        # Get file modification time
        mtime = log_path.stat().st_mtime
        last_run = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    # Calculate next run
    next_run = None
    if enabled and plist_exists:
        # Parse the plist to get the hour/minute
        import plistlib

        with open(PLIST_PATH, "rb") as f:
            plist = plistlib.load(f)
            interval = plist.get("StartCalendarInterval", {})
            hour = interval.get("Hour", 9)
            minute = interval.get("Minute", 0)

            now = datetime.now()
            next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_time <= now:
                # Next run is tomorrow
                from datetime import timedelta

                next_time += timedelta(days=1)
            next_run = next_time.strftime("%Y-%m-%d %H:%M:%S")

    return ScheduleStatus(
        enabled=enabled,
        plist_exists=plist_exists,
        last_run=last_run,
        next_run=next_run,
    )
