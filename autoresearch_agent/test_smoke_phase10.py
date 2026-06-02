"""Phase 10 smoke test — exercise director_one_cycle with mocked LLM + sandbox.

Run from the autoresearch_agent/ directory:

    python3 test_smoke_phase10.py

Exits 0 on success, non-zero on assertion failure. No external test deps —
the test patches `query_llm` and `run_in_sandbox` directly so it doesn't
need a live inference backend.

Covers:
  - Happy path: Analyst + K parallel CodeGens + K parallel EvalWorkers,
    no SelfHealer activation. Asserts parallel CodeGens by timing.
  - SelfHealer path: 2 of 3 CodeGens produce crashing code; Director must
    invoke SelfHealer on the crashed candidates and pick a survivor.
"""
import asyncio
import os
import sys
import tempfile
import time

# Run in a throwaway workdir so we don't leave checkpoint/population files in the source tree.
TMPDIR = tempfile.mkdtemp(prefix="phase10_smoke_")
os.chdir(TMPDIR)
with open("program.md", "w") as f:
    f.write("Smoke task: minimise val_loss.")
with open("train.py", "w") as f:
    f.write("print('val_loss 1.0')\n")

# Import after cwd switch in case anything resolves files relative to cwd at import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoresearch  # noqa: E402


def _extract_text(messages, role):
    for m in messages:
        if m.get("role") != role:
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
    return ""


calls = []


def fake_query_llm(messages, stream=True, temp=0.3):
    """Route based on prompt content. Sleeps 200ms so we can detect parallel dispatch."""
    sys_text = _extract_text(messages, "system")
    user_text = _extract_text(messages, "user")

    if "code analysis" in sys_text.lower():
        calls.append("analyst")
        return "1. weakness A\n2. weakness B\n3. weakness C"

    if "broken code" in user_text.lower() or "crashed" in user_text.lower():
        calls.append("healer")
        return "```python\nprint('val_loss 0.3')\n```"

    calls.append("codegen")
    time.sleep(0.2)  # parallelism probe
    return "```python\nprint('val_loss 0.6')\n```"


def fake_run_in_sandbox(code, workdir):
    """Return a CandidateResult based on a magic marker in the code."""
    if "CRASH_MARKER" in code:
        return autoresearch.CandidateResult(
            loss=float("inf"),
            output="Traceback (most recent call last):\n  ValueError: synthetic\n",
            code=code,
        )
    import re
    m = re.search(r"val_loss ([0-9.]+)", code)
    loss = float(m.group(1)) if m else 0.5
    return autoresearch.CandidateResult(
        loss=loss, output=f"val_loss {loss}\n", code=code
    )


def _assert(cond, msg):
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)


def _fresh_population():
    pop = autoresearch.Population()
    pop.members.append(
        autoresearch.PopulationMember(code="print('val_loss 1.0')", loss=1.0, cycle=0)
    )
    return pop


async def test_happy_path():
    print("\n=== Test 1: happy path — Analyst + 3 parallel CodeGens, no SelfHealer ===")
    calls.clear()

    autoresearch.query_llm = fake_query_llm
    autoresearch.run_in_sandbox = fake_run_in_sandbox

    t0 = time.monotonic()
    new_loss, _, _ = await autoresearch.director_one_cycle(
        iteration=1,
        max_iterations=3,
        population=_fresh_population(),
        best_loss=1.0,
        baseline_code="print('val_loss 1.0')",
        started_at="2026-01-01T00:00:00Z",
        experiment_log=[],
        history_prefix="",
        program_instructions="Smoke task.",
    )
    elapsed = time.monotonic() - t0

    role_counts = {r: calls.count(r) for r in set(calls)}
    _assert(role_counts.get("analyst", 0) == 1,
            f"want exactly 1 analyst call, got {role_counts}")
    _assert(role_counts.get("codegen", 0) == autoresearch.CANDIDATE_POOL_SIZE,
            f"want {autoresearch.CANDIDATE_POOL_SIZE} codegens, got {role_counts}")
    _assert(role_counts.get("healer", 0) == 0,
            f"want 0 healers on happy path, got {role_counts}")
    # 3 codegens × 200ms each. Serial: ~600ms. Parallel: ~200ms.
    _assert(elapsed < 0.5,
            f"codegens did not run in parallel — elapsed {elapsed:.2f}s ≥ 0.5s")
    _assert(new_loss < 1.0,
            f"want loss to improve from 1.0, got {new_loss}")

    print(f"[PASS] roles={role_counts}  loss 1.0 → {new_loss}  elapsed {elapsed:.2f}s")


async def test_self_healer():
    print("\n=== Test 2: SelfHealer fires when CodeGens produce crashing code ===")
    calls.clear()

    crash_pattern = [True, True, False]  # first two crash, third works
    counter = [0]

    def mixed_query(messages, stream=True, temp=0.3):
        sys_text = _extract_text(messages, "system")
        user_text = _extract_text(messages, "user")

        if "code analysis" in sys_text.lower():
            calls.append("analyst")
            return "1. weakness A"

        if "broken code" in user_text.lower() or "crashed" in user_text.lower():
            calls.append("healer")
            # Healed code prints a finite val_loss
            return "```python\nprint('val_loss 0.25')\n```"

        idx = counter[0]
        counter[0] += 1
        calls.append("codegen")
        if idx < len(crash_pattern) and crash_pattern[idx]:
            return "```python\n# CRASH_MARKER\nraise ValueError('boom')\n```"
        return "```python\nprint('val_loss 0.7')\n```"

    autoresearch.query_llm = mixed_query
    autoresearch.run_in_sandbox = fake_run_in_sandbox

    new_loss, _, _ = await autoresearch.director_one_cycle(
        iteration=1,
        max_iterations=3,
        population=_fresh_population(),
        best_loss=1.0,
        baseline_code="print('val_loss 1.0')",
        started_at="2026-01-01T00:00:00Z",
        experiment_log=[],
        history_prefix="",
        program_instructions="Smoke task.",
    )

    role_counts = {r: calls.count(r) for r in set(calls)}
    _assert(role_counts.get("healer", 0) >= 1,
            f"want at least 1 healer call when CodeGens crash, got {role_counts}")
    # Healed candidate prints val_loss 0.25 — should beat the surviving 0.7.
    _assert(new_loss <= 0.7,
            f"want best-of-survivors-and-healed, got {new_loss}")

    print(f"[PASS] roles={role_counts}  loss 1.0 → {new_loss}")


async def test_self_healer_disabled():
    print("\n=== Test 3: ENABLE_SELF_HEALER=false skips healer even when CodeGens crash ===")
    calls.clear()

    crash_pattern = [True, True, False]
    counter = [0]

    def mixed_query(messages, stream=True, temp=0.3):
        sys_text = _extract_text(messages, "system")
        if "code analysis" in sys_text.lower():
            calls.append("analyst")
            return "1. weakness A"
        idx = counter[0]
        counter[0] += 1
        calls.append("codegen")
        if idx < len(crash_pattern) and crash_pattern[idx]:
            return "```python\n# CRASH_MARKER\nraise ValueError('boom')\n```"
        return "```python\nprint('val_loss 0.7')\n```"

    autoresearch.query_llm = mixed_query
    autoresearch.run_in_sandbox = fake_run_in_sandbox
    original_flag = autoresearch.ENABLE_SELF_HEALER
    autoresearch.ENABLE_SELF_HEALER = False
    try:
        new_loss, _, _ = await autoresearch.director_one_cycle(
            iteration=1,
            max_iterations=3,
            population=_fresh_population(),
            best_loss=1.0,
            baseline_code="print('val_loss 1.0')",
            started_at="2026-01-01T00:00:00Z",
            experiment_log=[],
            history_prefix="",
            program_instructions="Smoke task.",
        )
    finally:
        autoresearch.ENABLE_SELF_HEALER = original_flag

    role_counts = {r: calls.count(r) for r in set(calls)}
    _assert(role_counts.get("healer", 0) == 0,
            f"want 0 healers when flag is off, got {role_counts}")
    _assert(new_loss <= 0.7, f"surviving codegen should still win, got {new_loss}")
    print(f"[PASS] roles={role_counts}  loss 1.0 → {new_loss}")


async def main():
    print(f"[smoke] cwd={os.getcwd()}")
    await test_happy_path()
    await test_self_healer()
    await test_self_healer_disabled()
    print("\n[ALL PASSED]")


if __name__ == "__main__":
    asyncio.run(main())
