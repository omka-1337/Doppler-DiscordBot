"""Where the bot's log files live, and which one is current.

Both containers need to agree on this: the bot writes, the dashboard tails and
serves. Keeping it in one module means the answer cannot drift between them.
"""

from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Timestamped so a restart never overwrites the previous run's log, and so that
# sorting by name is the same as sorting by time.
_STAMP = "%Y-%m-%d_%H-%M-%S"
_PATTERN = "doppler-*.log"

# Old runs are worth keeping to compare against, but not without a ceiling.
MAX_LOG_FILES = 25


def all_logs() -> list[Path]:
    """Every log file, newest first."""
    return sorted(LOG_DIR.glob(_PATTERN), reverse=True)


def current_log() -> Path | None:
    """The run that is being written now, or the most recent one."""
    logs = all_logs()
    return logs[0] if logs else None


def prune(keep: int = MAX_LOG_FILES) -> list[Path]:
    """Delete all but the newest `keep` logs. Returns what was removed."""
    removed = []
    for path in all_logs()[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            # A log we cannot delete is not worth failing a startup over.
            pass
    return removed


def start_new_log(now: datetime | None = None) -> Path:
    """Open a file for this run and drop the oldest once there are too many."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime(_STAMP)
    path = LOG_DIR / f"doppler-{stamp}.log"
    # Appending rather than truncating: two starts inside the same second would
    # otherwise lose the first one's lines.
    path.touch(exist_ok=True)
    prune()
    return path
