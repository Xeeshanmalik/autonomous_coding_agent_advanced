"""Synchronous self-healing inner loop (legacy).

What this module does
---------------------
``execute_and_heal`` runs a script and, on failure, repeatedly asks the LLM for a
surgical fix (feeding back the traceback) until it succeeds or exhausts its
retries.

Why it exists
-------------
This was the original single-threaded self-healing strategy. The Phase-10 harness
superseded it with ``agents.self_healer_agent``, which repairs crashed candidates
in parallel and per-candidate.

How it fits the architecture
----------------------------
Depends on ``prompts`` (``SYSTEM_PROMPT``), ``llm`` (``query_llm``) and ``parsing``
(``extract_code_block``).

NOTE (flagged, unchanged): ``execute_and_heal`` is **not called** anywhere in the
current codebase — retained verbatim for reference / potential reuse. The live
self-healing path is ``agents.self_healer_agent``.
"""

import os
import subprocess
from typing import Optional, Tuple

from ara import llm
from ara.parsing import extract_code_block
from ara.prompts import SYSTEM_PROMPT


def execute_and_heal(initial_code: str, max_retries: int = 3) -> Optional[Tuple[str, str]]:
    """Run ``initial_code`` as train.py and attempt to self-heal on failure.

    Algorithm
    ---------
    1. Write ``code`` to train.py and execute it via subprocess.
    2. If the process exits cleanly (returncode == 0) → return ``(stdout, code)``.
    3. If it fails: capture the traceback, build a targeted repair prompt, query
       the LLM for a corrected script, replace ``code``, and retry.
    4. After ``max_retries`` failed heals, log and return ``None``.

    Parameters
    ----------
    initial_code : str   – The Python source code to execute.
    max_retries  : int   – Maximum LLM-assisted fix attempts before giving up.

    Returns
    -------
    ``(stdout_output, final_code)`` on success, or ``None`` if all heals fail.
    """
    code = initial_code
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"  # Keep training strictly on CPU

    for attempt in range(max_retries + 1):  # attempt 0 = first run, 1..max = heals

        # --- Write the current code to disk ---
        with open("train.py", "w") as f:
            f.write(code)

        label = "initial execution" if attempt == 0 else f"heal attempt {attempt}/{max_retries}"
        print(f"[*] Running train.py ({label})…")

        # --- Execute: capture stdout and stderr SEPARATELY for precise diagnosis ---
        try:
            proc = subprocess.run(
                ["python", "train.py"],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("[-] Script timed out after 300 s.")
            if attempt == max_retries:
                print("[-] Self-healer exhausted all retries (timeout). Giving up.")
                return None
            # Feed timeout as error context so LLM can optimise runtime
            stderr_snapshot = "TimeoutError: Script exceeded 300-second execution limit. Optimise for speed."
        else:
            stdout_snapshot = proc.stdout
            stderr_snapshot = proc.stderr

            if proc.returncode == 0:

                print("[+] Script executed successfully.")
                return stdout_snapshot, code

            # Non-zero exit: print the FULL traceback to the operator log
            print(f"[-] Script exited with code {proc.returncode}.")
            if stderr_snapshot.strip():
                print("    STDERR ↓")
                print(stderr_snapshot.strip())

            # Cap stderr sent to the LLM repair prompt to the last 100 lines.
            # Long tracebacks from complex generated scripts can push the heal
            # prompt over the server's 4096-token context limit ("Error in
            # input stream"). The full output is already printed above for ops.
            stderr_lines = stderr_snapshot.strip().splitlines()
            if len(stderr_lines) > 100:
                stderr_snapshot = (
                    "[... truncated — showing last 100 lines ...]\n"
                    + "\n".join(stderr_lines[-100:])
                )

        # --- Healing exhausted? ---
        if attempt == max_retries:
            print(f"[-] Self-healer exhausted all {max_retries} repair attempts. Giving up on this code.")
            return None

        # --- Build a surgical repair prompt for the LLM ---
        print(f"[*] Querying LLM for a surgical fix (heal {attempt + 1}/{max_retries})…")

        repair_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "The following Python script raised a runtime error. "
                    "Your ONLY task is to return the FULLY CORRECTED script inside a ```python block. "
                    "Do NOT explain anything. Do NOT change the algorithm logic — fix ONLY the bug.\n\n"
                    f"=== BROKEN CODE ===\n```python\n{code}\n```\n\n"
                    f"=== FULL ERROR TRACEBACK ===\n{stderr_snapshot}\n\n"
                    "Return the complete, corrected Python script now."
                ),
            },
        ]

        try:
            llm_response = llm.query_llm(repair_messages)
        except Exception as e:
            print(f"[-] LLM query failed during healing: {e}")
            return None

        fixed_code = extract_code_block(llm_response)
        if not fixed_code:
            print("[-] LLM did not return a parseable code block. Retrying healing prompt…")
            # Keep `code` unchanged so we retry with the same broken version + same error
            continue

        print("[*] LLM returned a candidate fix. Applying and re-testing…")
        code = fixed_code  # Use the fixed code in the next loop iteration
