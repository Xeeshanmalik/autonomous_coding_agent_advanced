# Generic `program.md` Template

Paste this into the **Task** field in the frontend (or write it to
`program.md` directly when calling `POST /run`). It is intentionally
dataset-agnostic — no specific column names or domain vocabulary — so the
bootstrap and evolution steps can adapt to whatever CSV you upload.

Rationale: the autoresearch bootstrap already inspects `DATASET_PATH`
to learn the real column names, detect date formats, and write a runnable
baseline against the actual schema. The only thing a generic `program.md`
needs to communicate is the task *type* (regression vs classification),
the target column (or "use the last column"), and the constraints. Hard-
coding feature names from a different dataset confuses the LLM (see PR #25
for the mismatch-detection safety net).

---

```markdown
# AutoResearch Task

## Objective
Build a model that minimises `val_loss` on the uploaded dataset. The
bootstrap step writes a runnable baseline from your CSV's actual columns;
evolution iterates on it.

## Task Type
Choose one — delete the others before submitting:
- **Regression** — target is numeric; loss is Mean Squared Error.
- **Classification** — target is categorical; loss is 1 − accuracy.

## Target
Name the column to predict, or leave blank to default to the last column
of the uploaded CSV.

Target column: <fill in or leave blank>

## Dataset
Uploaded via the frontend, read by the bootstrap from `DATASET_PATH`.
Column names, date formats, and feature types are detected automatically.

## Constraints
- Libraries: Python 3.9 stdlib + `pandas`, `numpy`, `scipy`, `scikit-learn`.
- Compute: CPU-only. `n_jobs=1` everywhere.
- Per-candidate runtime: under 90 seconds.
- Code style: PEP 8.

## Success Criteria
- A 10% reduction in `val_loss` compared to the bootstrap baseline.
```

---

## What's dataset-specific (and what is not)

- **Dataset-specific (user fills in):** the target column name, if known.
- **Dataset-agnostic (handled by the system):**
  - Column-name discovery — `_extract_column_names` reads the CSV header.
  - Date-format detection — `_detect_date_columns` tries 16 common formats.
  - Schema mismatch guarding — `_detect_task_column_mismatch` flags any
    backticked column references in your task that don't exist in the
    uploaded CSV.
  - Baseline generation — the bootstrap LLM is told to use only the
    actual columns, and to default to the last column if no target is
    named.

## What happens if you forget and use a domain-specific template

The system degrades gracefully:

1. The bootstrap reads your actual CSV columns and lists them as
   "Available columns" in the LLM prompt.
2. Backticked column references in your task that don't exist in the CSV
   trigger a `[!]` console warning and a "task/dataset mismatch detected"
   block in the LLM prompt, telling the model to ignore the task's column
   names.
3. The LLM picks the target by best-match against the task wording, or
   falls back to the last column.

You'll get a working baseline either way — but using the generic template
above gives the LLM a clean signal and avoids the mismatch-warning path.
