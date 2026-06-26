"""``python -m ara`` entrypoint — equivalent to running the agent directly.

Delegates to ``ara.cli.run`` (which wraps ``main`` with the SIGTERM-aware
cancellation handler). The production server still launches the agent via the
top-level ``autoresearch.py`` shim to preserve its exact invocation contract;
this module exists so the package is also runnable on its own.
"""

from ara.cli import run

if __name__ == "__main__":
    run()
