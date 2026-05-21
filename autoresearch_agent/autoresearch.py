import os
import re
import subprocess
import requests
import json
import time

# ---------------------------------------------------------------------------
# LLM Endpoint Configuration
# ---------------------------------------------------------------------------
if os.environ.get("USE_GEMINI") == "true":
    LLM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/v1/chat/completions"
    MODEL = "models/gemini-2.0-flash"
    API_KEY = os.environ.get("GEMINI_API_KEY", "")
else:
    LLM_URL = os.getenv("LLM_BASE_URL", "http://local-deepseek-backend:8080/v1") + "/chat/completions"
    MODEL = os.getenv("LLM_MODEL", "deepSeek-R1-Distill-Qwen-32B")
    API_KEY = "dummy"


# ---------------------------------------------------------------------------
# System Prompt (shared between outer research loop and self-healer)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an elite autonomous research engineer. Output ONLY raw Python code inside ```python blocks. Do NOT output explanations or conversational text.

# YOUR ONLY JOB
Read the provided baseline script carefully. Understand what it is trying to do, then make it measurably better — lower val_loss. The task could be anything: data synthesis, regression, classification, optimisation, simulation, compression, etc. Your improvements must match the intent of the baseline.

# ABSOLUTE RULES

## Output
- Script MUST end with: `print(f'val_loss {score}')` where score is a float.
- The engine MINIMISES val_loss. Configure every metric so LOWER IS BETTER.
- Never remove or rename the val_loss print — the loop depends on it.

## Task Awareness (read baseline before writing)
- Understand what the baseline does BEFORE choosing an algorithm.
- If it generates synthetic data → improve the generation / distribution matching. Do NOT introduce supervised classifiers.
- If it trains a regressor → improve the regression model. Do NOT switch to a classifier.
- If it trains a classifier → improve classification. Do NOT switch to a regressor.
- When in doubt: keep the same algorithmic family as the baseline. Improve parameters, preprocessing, or training strategy only.

## Environment
- CPU-only sandbox. No GPU. Set `n_jobs=1` everywhere. Never use `-1`.
- Read data: `os.environ.get('DATASET_PATH', 'dataset.csv')`. No hardcoded paths.
- Only use: Python 3.9 stdlib, pandas, numpy, scipy, sklearn. Import everything explicitly.
- Do NOT use ctgan, copulas, torch, tensorflow, or any lib that requires installation.

## Code Quality
- Do not rewrite from scratch. Make surgical, mathematical improvements to the baseline.
- Never hallucinate function names. Verify every import exists in the library.
- If ERROR FEEDBACK is given: fix only that specific bug. Return the complete corrected script.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cmd(cmd, timeout=300):
    """Execute a shell command, returning combined stdout+stderr. CPU-only sandbox."""
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"  # Protect LLM VRAM by forcing scripts to CPU
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, env=env, timeout=timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"TimeoutError: Script execution exceeded {timeout} seconds!"


def extract_val_loss(output):
    """Parse val_loss from script output. Returns inf if not found."""
    match = re.search(r"val_loss[\s:=]+([0-9.]+)", output, re.IGNORECASE)
    return float(match.group(1)) if match else float("inf")


def extract_code_block(llm_text):
    """
    Pull the first ```python … ``` block out of LLM output.
    Falls back to everything after </think> for reasoning models.
    Returns the code string, or None if nothing usable is found.
    """
    # Strip <think>…</think> reasoning before searching
    text = re.sub(r"<think>.*?</think>", "", llm_text, flags=re.DOTALL)

    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: raw text after </think>
    if "</think>" in llm_text:
        tail = llm_text.split("</think>")[-1].strip()
        if tail:
            return tail

    return None


def query_llm(messages, stream=True):
    """
    Send a chat-completion request to the configured LLM endpoint.

    Handles:
      - Streaming responses (prints tokens in cyan, accumulates full text).
      - Exponential-backoff retry on HTTP 429.

    Returns the full accumulated response text, or raises on unrecoverable error.
    """
    headers = {"Content-Type": "application/json"}
    if os.environ.get("USE_GEMINI") == "true":
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.3,
        "stream": stream,
        # Hard cap on output tokens. Prompt is ~800 tokens; keeping total under
        # the server's 4096-token context (-c 4096) prevents "Error in input stream".
        # "max_tokens": 4096,
    }

    retry_count, max_retries, backoff = 0, 3, 10
    while True:
        response = requests.post(LLM_URL, json=payload, headers=headers, stream=stream)
        if response.status_code == 429 and retry_count < max_retries:
            print(f"\n[-] Rate limit hit (429). Retrying in {backoff}s… ({retry_count + 1}/{max_retries})")
            time.sleep(backoff)
            retry_count += 1
            backoff *= 2
            continue
        response.raise_for_status()
        break

    full_response = ""
    print("\033[96m", end="")  # Cyan text for LLM output

    for line in response.iter_lines():
        if line:
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if content is not None:
                        print(content, end="", flush=True)
                        full_response += content
                except json.JSONDecodeError:
                    pass

    print("\033[0m\n")  # Reset colour

    # Persist raw LLM response for offline debugging
    with open("last_llm_response.log", "w") as f:
        f.write(full_response)

    return full_response


# ---------------------------------------------------------------------------
# Self-Healing Inner Loop
# ---------------------------------------------------------------------------

def execute_and_heal(initial_code, max_retries=3):
    """
    Run `initial_code` as train.py and attempt to self-heal on failure.

    Algorithm
    ---------
    1. Write `code` to train.py and execute it via subprocess.
    2. If the process exits cleanly (returncode == 0) → return (stdout, code).
    3. If the process fails:
       a. Capture the full stderr traceback.
       b. Build a targeted repair prompt containing the broken code + traceback.
       c. Query the LLM for a corrected script.
       d. Replace `code` with the LLM's fix and go back to step 1.
    4. After `max_retries` failed healing attempts, log the failure and return None.

    Parameters
    ----------
    initial_code : str   – The Python source code to execute.
    max_retries  : int   – Maximum LLM-assisted fix attempts before giving up.

    Returns
    -------
    (stdout_output : str, final_code : str)  on success.
    None                                      if all healing attempts are exhausted.
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
            llm_response = query_llm(repair_messages)
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


# ---------------------------------------------------------------------------
# Outer Evolutionary Research Loop
# ---------------------------------------------------------------------------

def main():
    print("[*] Booting AutoResearch Agent with Self-Healing Inner Loop…")

    # --- Baseline evaluation ---
    print("[*] Running initial baseline evaluation…")
    baseline_output = run_cmd("python train.py")
    best_loss = extract_val_loss(baseline_output)
    if best_loss == float("inf"):
        print(
            "[!] Baseline script did not output a 'val_loss'. "
            "The AI will invent an appropriate metric and beat Infinity."
        )
    print(f"[*] Baseline val_loss established: {best_loss}")

    with open("program.md", "r") as f:
        program_instructions = f.read()

    # Save the original baseline code once — always send this to the LLM so
    # the prompt size stays fixed across all cycles (prevents context overflow
    # that caused empty responses after a breakthrough on cycle 2+).
    with open("train.py", "r") as f:
        baseline_code = f.read()

    iteration = 1
    max_iterations = int(os.environ.get("MAX_ITERATIONS", 5))

    while iteration <= max_iterations:
        print(f"\n{'='*50}")
        print(f"--- AutoResearch Cycle {iteration} ---")

        # Read the current champion code
        with open("train.py", "r") as f:
            current_code = f.read()

        # Rate-limit mitigation for Gemini
        if iteration > 1 and os.environ.get("USE_GEMINI") == "true":
            print("[*] Rate-limit mitigation: sleeping 5 s before next cycle…")
            time.sleep(5)

        model_name = "Gemini-2.0-Flash" if os.environ.get("USE_GEMINI") == "true" else "DeepSeek-32B"
        print(f"[*] Querying {model_name} for architectural improvements…\n")

        # Always send the original baseline code to the LLM (not the champion).
        # This keeps the prompt token count stable and lets each cycle attempt
        # a fresh improvement from the same known-good starting point.
        user_content = (
            f"{program_instructions}\n\nBaseline train.py (improve upon this):\n```python\n{baseline_code}\n```"
        )

        research_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # --- Query the LLM for an improved candidate ---
        try:
            llm_response = query_llm(research_messages)
        except Exception as e:
            print(f"\n[-] LLM query failed: {e}")
            # Restore champion code so the file is never left in a broken state
            with open("train.py", "w") as f:
                f.write(current_code)
            iteration += 1
            continue

        new_code = extract_code_block(llm_response)
        if not new_code:
            print("[-] Agent failed to format code properly. Skipping cycle.")
            iteration += 1
            continue

        # -----------------------------------------------------------------------
        # 🔧 SELF-HEALING INNER LOOP
        # Pass the LLM's new code to execute_and_heal(). It will run it, and if
        # it crashes, feed the traceback back to the LLM for up to 3 repair
        # attempts before declaring the cycle a failure.
        # -----------------------------------------------------------------------
        heal_result = execute_and_heal(new_code, max_retries=3)

        if heal_result is None:
            # All healing attempts failed — revert to the last known-good code
            print("[-] Self-healer could not recover the script. Reverting to previous champion.")
            with open("train.py", "w") as f:
                f.write(current_code)
            iteration += 1
            continue

        exec_output, healed_code = heal_result
        new_loss = extract_val_loss(exec_output)

        if new_loss == float("inf"):
            # Script ran without error but forgot to print val_loss
            print("[-] Script completed but did not emit 'val_loss'. Reverting.")
            print(exec_output.strip() or "No output")
            with open("train.py", "w") as f:
                f.write(current_code)
            iteration += 1
            continue

        print(f"[*] Evaluated new val_loss: {new_loss}")

        if new_loss < best_loss:
            print(f"[+] BREAKTHROUGH! Loss improved: {best_loss:.6f} → {new_loss:.6f}")
            best_loss = new_loss
            # Write the winner (healed_code may differ from new_code if healing ran)
            with open("train.py", "w") as f:
                f.write(healed_code)
        else:
            print(f"[-] No improvement ({new_loss:.6f} ≥ {best_loss:.6f}). Reverting to previous champion.")
            with open("train.py", "w") as f:
                f.write(current_code)

        iteration += 1

    print(f"\n{'='*50}")
    print(f"[*] AutoResearch Loop Completed! Final val_loss: {best_loss}")


if __name__ == "__main__":
    main()