"""Process lifecycle & cooperative cancellation (Phase 9).

What this module does
---------------------
Installs a SIGTERM handler that flips a module-level flag, and exposes
``_check_cancel`` so long-running work (chiefly LLM streaming) can poll that flag
and abort cleanly. The server's ``/cancel`` endpoint sends SIGTERM to the run's
process group; this module is how the agent notices.

Why it exists
-------------
Cancellation has to be observable from deep inside the LLM streaming loop without
threading a flag through every call signature. A module-level flag mutated by the
signal handler is the simplest mechanism that works across the whole package.

How it fits the architecture
----------------------------
Leaf module imported by the LLM transport (to interrupt a stream) and by the
orchestrator (to stop the cycle loop). The handler is registered at import time —
importing the package installs it, matching the original single-file behaviour.

Access pattern note
-------------------
``_sigterm_received`` is mutated at runtime, so readers access it via attribute
(``lifecycle._sigterm_received``) rather than importing the name, to always see
the current value.
"""

import signal
from typing import Any, Optional

# Set True by the SIGTERM handler; read by _check_cancel and the orchestrator loop.
_sigterm_received: bool = False


def _handle_sigterm(signum: int, frame: Any) -> None:
    """SIGTERM handler: request a graceful stop after the current cycle.

    Wired to SIGTERM at import. The server's /cancel endpoint sends SIGTERM
    first (then escalates to SIGKILL) so the agent can close the LLM socket
    and let the inference server abort generation immediately.
    """
    global _sigterm_received
    print("[!] SIGTERM received — will exit after the current cycle completes.")
    _sigterm_received = True


signal.signal(signal.SIGTERM, _handle_sigterm)


def _check_cancel(response: Optional[Any] = None, when: str = "before LLM call") -> None:
    """Raise KeyboardInterrupt if cancellation was requested.

    Polled by the LLM streaming backends before a request and again per
    streamed line. When a live ``response`` is passed, its socket is closed
    first so the inference server stops generating tokens at once.
    """
    if _sigterm_received:
        if response is not None:
            response.close()
            print("\033[0m\n[!] LLM stream aborted — cancellation requested.")
        raise KeyboardInterrupt(f"cancellation requested {when}")
