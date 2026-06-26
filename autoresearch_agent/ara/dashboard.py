"""Frontend dashboard telemetry.

What this module does
---------------------
Streams machine-readable chart data to the frontend and stages the export helper:
  - ``emit_event`` — print one ``__EVENT__{json}`` line the frontend dispatches on.
  - ``_downsample`` — cap a series to ``DASHBOARD_MAX_POINTS`` points defensively.
  - ``_ensure_dashboard_helper`` — copy ``dashboard_export.py`` into the per-run
    working dir so champion scripts can ``import dashboard_export``.
  - ``emit_dashboard_data`` — run the final champion once to produce
    ``dashboard.json`` and stream it as a ``predictions`` event.

Why it exists
-------------
Telemetry must never be able to break a run, so every function here is
best-effort and swallows its own errors. Centralising it keeps that guarantee in
one place and off the critical path.

How it fits the architecture
----------------------------
Depends on ``config`` (``EVENT_PREFIX`` / ``DASHBOARD_MAX_POINTS``) and ``sandbox``
(``run_cmd``). ``emit_event`` is called by the orchestrator each cycle;
``_ensure_dashboard_helper`` and ``emit_dashboard_data`` are called by ``cli``.

Path note (changed for the package layout)
------------------------------------------
``_ensure_dashboard_helper`` resolves ``dashboard_export.py`` relative to the
**package parent** (``dirname(dirname(__file__))``) because this module now lives
at ``ara/dashboard.py`` while the helper sits alongside the top-level shim. The
file staged into the cwd is identical to before — only the source path math
changed.
"""

import json
import os
import shutil
from typing import Any, List

from ara import config
from ara.sandbox import run_cmd


def emit_event(payload: dict) -> None:
    """Emit one machine-readable ``__EVENT__`` line for the frontend stream.

    Always a single compact line (the frontend splits the stream on ``\\n``) and
    never raises — telemetry must not be able to break a run.
    """
    try:
        print(config.EVENT_PREFIX + json.dumps(payload, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        pass


def _downsample(seq: Any, limit: int = config.DASHBOARD_MAX_POINTS) -> Any:
    """Uniformly subsample a list to at most ``limit`` points, preserving order.

    Defensive: the champion is asked to cap its own series, but we never trust a
    freeform script to comply. Non-list inputs and short lists pass through
    unchanged.
    """
    if not isinstance(seq, list) or len(seq) <= limit:
        return seq
    step = len(seq) / limit
    return [seq[min(len(seq) - 1, int(i * step))] for i in range(limit)]


def _ensure_dashboard_helper() -> None:
    """Copy ``dashboard_export.py`` into the current per-run working directory.

    Champion scripts ``import dashboard_export``; ``run_in_sandbox`` copies every
    file in the cwd into each candidate sandbox, so staging it here makes it
    available to candidates and to the final champion run alike. The source is
    resolved relative to the package parent (see module docstring). Best-effort —
    never blocks a run.
    """
    try:
        package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = os.path.join(package_parent, "dashboard_export.py")
        dst = os.path.join(os.getcwd(), "dashboard_export.py")
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    except Exception as e:  # noqa: BLE001 — never block a run on the helper
        print(f"[*] Could not stage dashboard_export helper: {e}")


def emit_dashboard_data() -> None:
    """Run the final champion once and stream its chart data to the frontend.

    Plain execution (NOT an LLM call): the champion writes ``dashboard.json`` per
    the SYSTEM_PROMPT contract, which is then downsampled and emitted as a single
    ``__EVENT__{"type":"predictions",...}`` line. Best-effort — any failure is
    swallowed so a missing chart never affects the run's exit status or the
    ``[FINAL_CODE_*]`` block.
    """
    try:
        if not os.path.exists("train.py"):
            return
        run_cmd("python train.py")  # champion writes dashboard.json per SYSTEM_PROMPT contract
        if not os.path.exists("dashboard.json"):
            print("[*] Champion produced no dashboard.json — skipping chart export.")
            return
        with open("dashboard.json", "r") as f:
            data = json.load(f)
        for key in ("target", "y_true", "y_pred"):
            if isinstance(data.get(key), list):
                data[key] = _downsample(data[key])
        # The Actual-vs-Predicted chart pairs y_true[i] with y_pred[i], so the
        # two must stay the same length and index-aligned. The helper already
        # guarantees this, but a champion that writes dashboard.json by hand may
        # not — truncate to the common length as a last-ditch safety net so the
        # actual/predicted lines can't drift apart.
        yt, yp = data.get("y_true"), data.get("y_pred")
        if isinstance(yt, list) and isinstance(yp, list) and len(yt) != len(yp):
            n = min(len(yt), len(yp))
            data["y_true"], data["y_pred"] = yt[:n], yp[:n]
        emit_event({"type": "predictions", **data})
        print("[*] Dashboard chart data streamed to frontend.")
    except Exception as e:  # noqa: BLE001 — chart export must never break the run
        print(f"[*] Dashboard export skipped: {e}")
