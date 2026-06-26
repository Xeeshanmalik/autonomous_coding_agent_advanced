"""Dataset introspection for the bootstrap prompt.

What this module does
---------------------
Pure, dataset-agnostic helpers that look at the uploaded CSV (or the task text)
and surface facts the LLM needs to write a correct baseline:
  - ``_read_dataset_preview`` — header + first few rows of the dataset.
  - ``_extract_column_names`` — the exact column names from that preview.
  - ``_detect_date_columns`` / ``_infer_date_format`` — explicit strftime formats
    so the LLM doesn't rely on pandas auto-inference (which mis-parses day-first).
  - ``_detect_task_column_mismatch`` — backticked identifiers in the task that are
    absent from the dataset (stale/generic template detection).

Why it exists
-------------
The biggest source of bootstrap failures is the LLM guessing wrong column names
or date formats. Feeding it ground truth derived from the actual file removes that
class of error — and keeping the logic here (separate from prompt assembly) makes
each heuristic independently testable (see ``test_bootstrap_generality.py`` and
``test_task_dataset_mismatch.py``).

How it fits the architecture
----------------------------
Leaf module: only ``datetime``, ``os``, ``re``. Consumed exclusively by
``bootstrap`` when constructing the baseline-generation prompt.
"""

import datetime
import os
import re
from typing import List, Tuple

DATE_FORMATS_TO_TRY: Tuple[str, ...] = (
    # Day-first is tried first because pandas auto-inference picks month-first
    # by default and silently crashes on DD-MM-YYYY datasets. Listing day-first
    # variants ahead of month-first means an unambiguous DD-MM-YYYY column
    # (one with day>12) gets the right format.
    "%d-%m-%Y", "%m-%d-%Y", "%Y-%m-%d",
    "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
    "%d.%m.%Y", "%m.%d.%Y",          # dot separator — German/French CSVs
    "%Y%m%d",                          # compact, no separator
    "%d-%m-%y", "%m-%d-%y", "%y-%m-%d",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 with µs / Z
)


def _infer_date_format(samples: List[str]):
    """Return the first strftime format that parses ALL non-empty samples, or None.

    Requires at least two distinct non-empty samples so we don't false-positive
    on a single ambiguous date like "01-02-2010" (could be d-m-Y or m-d-Y).
    Formats are tried in ``DATE_FORMATS_TO_TRY`` order, so day-first is preferred
    over month-first — the failure mode pandas auto-inference hits on DD-MM-YYYY
    datasets.
    """
    non_empty = [s.strip() for s in samples if s and s.strip()]
    if len(set(non_empty)) < 2:
        return None
    for fmt in DATE_FORMATS_TO_TRY:
        try:
            for s in non_empty:
                datetime.datetime.strptime(s, fmt)
            return fmt
        except (ValueError, TypeError):
            continue
    return None


def _extract_column_names(preview_text: str) -> List[str]:
    """Return the list of column names from the preview's header row.

    Surfaced separately from the preview itself because the LLM otherwise skims
    past the CSV header and hallucinates plausible-sounding column names (e.g.
    ``df['price']`` for a retail dataset whose actual target is ``Weekly_Sales``).
    The explicit list makes ANY other name an obvious bug.
    """
    lines = preview_text.strip().splitlines()
    if not lines:
        return []
    return [c.strip() for c in lines[0].split(",") if c.strip()]


# Words that look like `identifiers` in a task description but are clearly
# library / metric / framework references, not column names. Used by
# _detect_task_column_mismatch to avoid false-positive "column not in dataset"
# warnings on backticked code symbols.
_TASK_NON_COLUMN_WORDS = frozenset({
    # Libraries / frameworks
    "sklearn", "pandas", "numpy", "scipy", "scikit", "torch", "tensorflow",
    "pd", "np", "csv",
    # Common sklearn classes / functions seen in task descriptions
    "LinearRegression", "RandomForestRegressor", "GridSearchCV",
    "StandardScaler", "OneHotEncoder", "train_test_split",
    "mean_squared_error", "r2_score",
    # Metrics
    "MSE", "RMSE", "MAE", "R2", "AUC", "F1",
    # Pipeline tokens
    "train", "val", "test", "DATASET_PATH", "val_loss", "fit", "predict",
    "transform", "score", "model", "pipeline",
    # Other
    "Python", "PEP",
})


def _detect_task_column_mismatch(program_instructions: str,
                                 actual_columns: List[str]) -> List[str]:
    """Return backticked identifiers in the task that are NOT in the dataset.

    Helps detect the case where program.md uses a stale or generic template
    (real-estate examples like ``size`` / ``location`` / ``price``) while the
    uploaded CSV is something else (e.g. crude-oil prices). The mismatch lets us
    tell the LLM "ignore those names — the actual dataset is here".

    Identifier detection is intentionally crude: ``[a-zA-Z_][a-zA-Z0-9_]*``
    inside backticks. Library names, metrics, and common sklearn symbols are
    filtered via ``_TASK_NON_COLUMN_WORDS``. The result is a best-effort warning,
    not a hard error.
    """
    referenced = set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*)`", program_instructions))
    actual_lower = {c.lower() for c in actual_columns}
    suspicious = sorted(
        name for name in referenced
        if name not in _TASK_NON_COLUMN_WORDS
        and name.lower() not in actual_lower
    )
    return suspicious


def _detect_date_columns(preview_text: str) -> List[Tuple[str, str]]:
    """Return ``[(column_name, strftime_format), ...]`` for unambiguous date columns.

    Inspects a CSV preview string and reports every column whose sample values
    match a known date format unambiguously. Lets the bootstrap prompt give the
    LLM an explicit ``format='%d-%m-%Y'`` instead of letting ``pd.to_datetime``
    auto-infer (which silently picks month-first and crashes mid-column on
    day-first datasets).
    """
    lines = preview_text.strip().splitlines()
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split(",")]
    data_rows = [row.split(",") for row in lines[1:]]
    detected: List[Tuple[str, str]] = []
    for col_idx, col_name in enumerate(headers):
        samples = [
            r[col_idx].strip() if col_idx < len(r) else ""
            for r in data_rows
        ]
        fmt = _infer_date_format(samples)
        if fmt:
            detected.append((col_name, fmt))
    return detected


def _read_dataset_preview(max_rows: int = 5) -> str:
    """Return the dataset header + first ``max_rows`` data rows as a plain string.

    Returned to the LLM so the bootstrap baseline uses real column names instead
    of guessing 'target'. Returns "" if the file is missing or unreadable — the
    LLM then has to do its best from program.md alone, which is the previous
    behaviour. Reads the path from ``DATASET_PATH`` (default ``dataset.csv``).
    """
    path = os.environ.get("DATASET_PATH", "dataset.csv")
    if not os.path.exists(path):
        return ""
    try:
        lines = []
        with open(path, "r", errors="replace") as f:
            for i, line in enumerate(f):
                if i > max_rows:
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)
    except Exception as e:
        print(f"[!] Could not read dataset preview ({e}). Continuing without it.")
        return ""
