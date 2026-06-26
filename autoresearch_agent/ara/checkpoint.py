"""Run-state checkpointing and champion versioning (Phase 6).

What this module does
---------------------
Persists enough loop state to resume a crashed/cancelled run, and snapshots each
champion into git:
  - ``save_checkpoint`` / ``load_checkpoint`` — write/read ``checkpoint.json``
    (iteration, best loss, baseline code, history, summary prefix).
  - ``git_commit_champion`` — commit ``train.py`` to the run's local git repo on a
    breakthrough, building a history of champions.

Why it exists
-------------
Runs can be long and are cancellable; without checkpointing, an interruption loses
all progress. The git commits additionally give a per-cycle audit trail of how the
champion evolved.

How it fits the architecture
----------------------------
Depends only on ``config`` (``CHECKPOINT_PATH``) and the stdlib. ``cli`` calls
``load_checkpoint`` on startup; the orchestrator calls ``save_checkpoint`` every
cycle and ``git_commit_champion`` on a breakthrough.
"""

import json
import os
import subprocess
from typing import List, Optional

from ara import config


def save_checkpoint(iteration: int, best_loss: float, baseline_code: str,
                    started_at: str, experiment_log: Optional[List[dict]] = None,
                    history_prefix: str = "") -> None:
    """Persist loop state to ``checkpoint.json`` so a crashed run can resume.

    Stores ``best_loss=None`` for a non-finite loss so the JSON round-trips
    cleanly; ``load_checkpoint`` maps it back to ``inf``.
    """
    data = {
        "iteration": iteration,
        "best_loss": best_loss if best_loss != float("inf") else None,
        "baseline_code": baseline_code,
        "started_at": started_at,
        "experiment_log": experiment_log or [],
        "history_prefix": history_prefix,
    }
    with open(config.CHECKPOINT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[*] Checkpoint saved (iteration {iteration}, best_loss={best_loss:.6f}).")


def load_checkpoint() -> Optional[dict]:
    """Return the checkpoint dict if ``checkpoint.json`` exists and is valid, else None.

    Maps the persisted ``best_loss=None`` back to ``inf`` and back-fills missing
    keys so older checkpoints still load. A corrupt file logs a warning and
    returns ``None`` so the run starts fresh.
    """
    if not os.path.exists(config.CHECKPOINT_PATH):
        return None
    try:
        with open(config.CHECKPOINT_PATH) as f:
            data = json.load(f)
        loss = data["best_loss"] if data["best_loss"] is not None else float("inf")
        data.setdefault("experiment_log", [])
        data.setdefault("history_prefix", "")
        print(f"[*] Checkpoint found — resuming from iteration {data['iteration'] + 1}, best_loss={loss:.6f}.")
        return data
    except Exception as e:
        print(f"[!] Failed to load checkpoint ({e}). Starting fresh.")
        return None


def git_commit_champion(iteration: int, best_loss: float) -> None:
    """Commit the current ``train.py`` to local git history after a breakthrough.

    Non-fatal: if git isn't configured in the workdir, the failure is swallowed
    so the research loop continues regardless.
    """
    try:
        subprocess.run(["git", "add", "train.py"], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"cycle {iteration}: loss {best_loss:.6f}"],
            capture_output=True,
            check=True,
        )
        print(f"[*] Champion committed to git (cycle {iteration}: loss {best_loss:.6f}).")
    except subprocess.CalledProcessError:
        pass  # git not configured in this workdir — non-fatal
