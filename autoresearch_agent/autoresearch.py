"""AutoResearch entrypoint shim.

The agent's implementation now lives in the ``ara`` package (see
``ARCHITECTURE.md``). This file is kept ONLY as the process entrypoint so the
existing run contract is unchanged: ``server.py`` launches the agent with
``python -u autoresearch.py`` from the per-run working directory, and the
Dockerfile copies it to ``/research/autoresearch.py``.

All logic is in ``ara``; do not add behaviour here. Use ``python -m ara`` for the
equivalent module entrypoint.
"""

from ara.cli import run

if __name__ == "__main__":
    run()
