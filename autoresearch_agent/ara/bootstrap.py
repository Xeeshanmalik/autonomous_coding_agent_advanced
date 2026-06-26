"""Baseline bootstrap — refuse (or auto-write) when val_loss is undefined.

What this module does
---------------------
Gates the start of a run. When the user-supplied baseline does not print a finite
``val_loss``, the evolutionary loop has no signal to optimise. This module forces
a decision:
  - ``generate_baseline_from_task`` — ask the LLM to write a runnable baseline
    from program.md + a dataset preview (with optional error-hint retry).
  - ``bootstrap_baseline_if_needed`` — the gate itself: pass-through if the
    baseline already works; otherwise branch on ``BOOTSTRAP_MODE`` (auto = retry
    with the LLM, manual/unset = refuse with instructions).

Why it exists
-------------
Silently running every cycle against ``+inf`` wastes a whole run. Failing fast (or
auto-writing a baseline) is far more useful, and surfacing the choice via the
server's ``bootstrapMode`` field keeps the policy explicit.

How it fits the architecture
----------------------------
Depends on ``config`` (``BOOTSTRAP_MAX_ATTEMPTS``), ``llm`` (``query_llm``),
``prompts`` (``SYSTEM_PROMPT``), ``parsing`` (``extract_code_block`` /
``extract_val_loss``), ``sandbox`` (``run_cmd``), and ``dataset_introspect``.
Called once by ``cli.main`` before the cycle loop. ``raise SystemExit(2)``
propagates out through ``main`` to end the streamed ``/run`` cleanly.
"""

import math
import os
from typing import Optional, Tuple

from ara import config, llm
from ara.dataset_introspect import (
    _detect_date_columns,
    _detect_task_column_mismatch,
    _extract_column_names,
    _read_dataset_preview,
)
from ara.parsing import extract_code_block, extract_val_loss
from ara.prompts import SYSTEM_PROMPT
from ara.sandbox import run_cmd

BOOTSTRAP_REFUSE_MSG = (
    "[-] Baseline script did not output a 'val_loss' line.\n"
    "    The evolutionary loop cannot start from val_loss=inf.\n"
    "    Either:\n"
    "      • Fix your baseline to end with `print(f'val_loss {score}')` (manual mode), or\n"
    "      • Re-run with bootstrapMode='auto' and the LLM will write a baseline for you."
)


def generate_baseline_from_task(program_instructions: str,
                                error_hint: Optional[str] = None) -> Optional[str]:
    """Ask the LLM for a minimal runnable baseline derived from program.md.

    Includes a small dataset preview and, when ``error_hint`` is supplied (e.g.
    the traceback from a previous failed attempt), the prior error so the LLM
    fixes the specific bug rather than guessing again. Also injects authoritative
    column names, detected date formats, and a task/dataset mismatch warning when
    the uploaded CSV disagrees with the task text.

    Returns the extracted code string, or ``None`` if the LLM call failed or did
    not produce a parseable ```python block.
    """
    dataset_preview = _read_dataset_preview()
    dataset_path = os.environ.get("DATASET_PATH", "dataset.csv")

    columns_block = ""
    date_hints_block = ""
    mismatch_block = ""
    if dataset_preview:
        columns = _extract_column_names(dataset_preview)
        if columns:
            columns_block = (
                "\n\nAvailable columns (use ONLY these exact names — any other name "
                "will KeyError):\n  " + ", ".join(columns)
            )
            # Detect when the task description references columns that are not
            # in the uploaded dataset — common when program.md is a stale
            # template and the user uploaded a different CSV.
            mismatch = _detect_task_column_mismatch(program_instructions, columns)
            if mismatch:
                print(f"[!] Task description references columns NOT in the uploaded "
                      f"dataset: {mismatch}.")
                print(f"    Actual dataset columns: {columns}")
                print(f"    Bootstrap will instruct the LLM to ignore the task's "
                      f"column names and use the dataset's actual ones.")
                mismatch_block = (
                    "\n\nIMPORTANT — task/dataset mismatch detected. "
                    f"The task description references column names that do NOT exist in "
                    f"the uploaded dataset: {', '.join(mismatch)}. "
                    "The task is a generic / stale template; the uploaded CSV is what "
                    "matters. IGNORE those names. Use ONLY the 'Available columns' "
                    "above. Pick the target column by best semantic match in the "
                    "actual list (e.g. anything that looks like a price/score/value), "
                    "or fall back to the last column."
                )
        detected_dates = _detect_date_columns(dataset_preview)
        if detected_dates:
            lines = [
                f"  - df['{name}']: use pd.to_datetime(df['{name}'], format='{fmt}')"
                for name, fmt in detected_dates
            ]
            date_hints_block = (
                "\n\nDate columns (use these exact formats — do NOT rely on auto-inference):\n"
                + "\n".join(lines)
            )

    dataset_block = (
        f"\n\nDataset preview ({dataset_path}):\n```\n{dataset_preview}\n```"
    ) if dataset_preview else ""

    error_block = (
        f"\n\nPrevious attempt failed with this traceback — fix the SPECIFIC bug "
        f"(do not repeat the same mistake):\n```\n{error_hint}\n```"
    ) if error_hint else ""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Write a minimal, runnable Python baseline for the task below.\n"
            "Rules:\n"
            "- Must end with `print(f'val_loss {score}')` (finite float).\n"
            "- Also export the dashboard in one line: `import dashboard_export; dashboard_export.dump(target_name=..., target=..., y_true=..., y_pred=..., mse=...)` (helper already in the working dir). Pass VALIDATION-only rows to target/y_true/y_pred (the held-out split, NOT the full column or training rows) so both charts cover the same rows; mse is the val MSE.\n"
            "- Must run in <90 s. No GridSearchCV with big grids, no n_estimators>50, no nested CV.\n"
            "- Stdlib + pandas, numpy, scipy, sklearn only. Read data from `os.environ.get('DATASET_PATH', 'dataset.csv')`.\n"
            "- The 'Available columns' list below is AUTHORITATIVE. If the task description mentions a column name that is NOT in that list, IGNORE it — the task may be a generic/stale template. Use ONLY columns from the list. Pick target by best name match against the task; if no match, the last column in the list.\n"
            "- Don't `pd.get_dummies` on Date/ID columns — derive features (Day/Month/Year) or drop them.\n\n"
            f"Task:\n{program_instructions}"
            f"{columns_block}"
            f"{mismatch_block}"
            f"{dataset_block}"
            f"{date_hints_block}"
            f"{error_block}"
            "\n\nOutput ONLY the Python code inside a ```python block."
        )},
    ]
    print("[*] Bootstrap: asking LLM to write a baseline…"
          + (" (retry with error hint)" if error_hint else ""))
    try:
        response = llm.query_llm(messages)
    except Exception as e:
        print(f"[-] LLM call failed during bootstrap: {e}")
        return None
    return extract_code_block(response)


def bootstrap_baseline_if_needed(best_loss: float,
                                 program_instructions: str) -> Tuple[float, str]:
    """Gate the loop: if val_loss is non-finite, branch on ``BOOTSTRAP_MODE``.

    In ``auto`` mode, retries up to ``BOOTSTRAP_MAX_ATTEMPTS`` times, feeding the
    previous traceback back to the LLM each retry so it can fix specific bugs
    (wrong column name, missing import, etc.) instead of starting fresh.

    Returns ``(best_loss, baseline_code)`` on success. Raises ``SystemExit(2)``
    when no valid baseline can be produced — that exit propagates through
    ``main()`` and ends the streamed ``/run`` cleanly with the refusal message.
    """
    if math.isfinite(best_loss):
        with open("train.py", "r") as f:
            return best_loss, f.read()

    mode = os.environ.get("BOOTSTRAP_MODE", "").strip().lower()
    if mode != "auto":
        # manual or unset — refuse without invoking the LLM
        print(BOOTSTRAP_REFUSE_MSG)
        raise SystemExit(2)

    error_hint: Optional[str] = None
    last_output = ""
    for attempt in range(1, config.BOOTSTRAP_MAX_ATTEMPTS + 1):
        print(f"[*] Bootstrap attempt {attempt}/{config.BOOTSTRAP_MAX_ATTEMPTS}…")
        generated = generate_baseline_from_task(program_instructions, error_hint=error_hint)
        if not generated:
            error_hint = "Previous response did not contain a parseable ```python block."
            continue

        with open("train.py", "w") as f:
            f.write(generated)
        regen_output = run_cmd("python train.py")
        last_output = regen_output
        new_loss = extract_val_loss(regen_output)
        if math.isfinite(new_loss):
            print(f"[*] Bootstrap succeeded on attempt {attempt} — val_loss={new_loss:.6f}")
            return new_loss, generated

        # Capture tail of the output as the error hint for the next attempt.
        # Use 200 lines, not 80 — sklearn/pandas tracebacks include a deep
        # stack of internal frames plus deprecation noise, and the actual
        # exception summary can sit above an 80-line window.
        error_lines = regen_output.strip().splitlines()
        error_hint = "\n".join(error_lines[-200:]) if error_lines else "Script exited without producing val_loss."
        print(f"[-] Attempt {attempt} produced no finite val_loss; will retry with traceback.")

    print(f"[-] All {config.BOOTSTRAP_MAX_ATTEMPTS} bootstrap attempts failed.")
    print("    Last script output ↓")
    print(last_output[-3000:])
    print(BOOTSTRAP_REFUSE_MSG)
    raise SystemExit(2)
