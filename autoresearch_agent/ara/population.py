"""Population-based selection — the evolutionary memory (Phase 2).

What this module does
---------------------
Maintains the small population of champion-quality scripts the search evolves:
  - ``PopulationMember`` / ``Population`` — the data structures + JSON persistence.
  - ``select_parent`` — softmax-weighted parent choice (lower loss → more likely).
  - ``update_population`` — admit a new member if there's room or it beats the worst.
  - ``save_population`` / ``load_population`` — persist to / restore from disk.

Why it exists
-------------
Keeping a population (rather than a single champion) lets the search escape local
minima: weaker-but-diverse members can still be selected as parents. This module
owns that state and the policy for evolving it.

How it fits the architecture
----------------------------
Depends only on ``config`` (``POPULATION_SIZE``, ``SELECT_PARENT_BETA``,
``POPULATION_PATH``) and the stdlib. The orchestrator reads/writes the population
each cycle; ``cli`` loads it on resume.
"""

import json
import math
import os
import random
from dataclasses import dataclass
from typing import List, Optional

from ara import config


@dataclass
class PopulationMember:
    """One script in the population: its ``code``, its ``loss``, and the ``cycle``
    that produced it. Members are ranked purely by ``loss`` (lower is better)."""
    code: str
    loss: float
    cycle: int


class Population:
    """The bounded set of best-so-far scripts the search evolves (Phase 2).

    Holds at most ``size`` members. The orchestrator selects a parent from it
    each cycle, then offers the cycle's best candidate back via
    ``update_population``.
    """

    def __init__(self, size: int = config.POPULATION_SIZE) -> None:
        self.size = size
        self.members: List[PopulationMember] = []

    def is_full(self) -> bool:
        """True once the population has reached its configured size."""
        return len(self.members) >= self.size

    def best(self) -> PopulationMember:
        """Return the lowest-loss member (the current champion)."""
        return min(self.members, key=lambda m: m.loss)

    def worst(self) -> PopulationMember:
        """Return the highest-loss member (the eviction candidate)."""
        return max(self.members, key=lambda m: m.loss)

    def to_json(self) -> list:
        """Serialise members to a plain list of dicts for ``population.json``."""
        return [{"code": m.code, "loss": m.loss, "cycle": m.cycle} for m in self.members]

    @classmethod
    def from_json(cls, data: list, size: int = config.POPULATION_SIZE) -> "Population":
        """Rebuild a ``Population`` from the serialised member list."""
        pop = cls(size=size)
        pop.members = [
            PopulationMember(code=d["code"], loss=d["loss"], cycle=d["cycle"])
            for d in data
        ]
        return pop


def select_parent(population: Population) -> PopulationMember:
    """Softmax-weighted selection: lower loss → higher probability of being chosen.

    Weights are ``exp(-beta * (l - min_loss) / spread)``. Normalising by the
    spread keeps the exponent bounded regardless of loss magnitude — without it,
    losses like 1500 vs 0.3 (a crashed baseline alongside good members) push
    ``math.exp`` past its overflow threshold (~709) and crash the loop.
    Non-finite losses get weight 0 so a crashed member is never selected.
    """
    if len(population.members) == 1:
        return population.members[0]
    losses = [m.loss for m in population.members]
    finite = [l for l in losses if math.isfinite(l)]
    if not finite:
        return random.choice(population.members)
    min_loss = min(finite)
    spread = max(finite) - min_loss
    T = spread if spread > 0 else 1.0
    weights = [
        math.exp(-config.SELECT_PARENT_BETA * (l - min_loss) / T) if math.isfinite(l) else 0.0
        for l in losses
    ]
    total = sum(weights)
    if total == 0:
        return random.choice(population.members)
    r = random.random() * total
    cumulative = 0.0
    for member, w in zip(population.members, weights):
        cumulative += w
        if r <= cumulative:
            return member
    return population.members[-1]


def update_population(population: Population, new_member: PopulationMember) -> bool:
    """Add ``new_member`` if the population has room or it beats the worst member.

    Returns ``True`` if admitted (the caller uses this to decide whether to
    persist train.py), ``False`` if rejected.
    """
    if not population.is_full():
        population.members.append(new_member)
        return True
    worst = population.worst()
    if new_member.loss < worst.loss:
        population.members.remove(worst)
        population.members.append(new_member)
        return True
    return False


def save_population(population: Population) -> None:
    """Persist the population to ``population.json`` in the working directory."""
    with open(config.POPULATION_PATH, "w") as f:
        json.dump({"size": population.size, "members": population.to_json()}, f, indent=2)


def load_population() -> Optional[Population]:
    """Restore the population from ``population.json``, or ``None`` if absent/corrupt.

    Called by ``cli`` on resume. A corrupt file logs a warning and returns
    ``None`` so the run starts fresh rather than crashing.
    """
    if not os.path.exists(config.POPULATION_PATH):
        return None
    try:
        with open(config.POPULATION_PATH) as f:
            data = json.load(f)
        pop = Population.from_json(data["members"], size=data.get("size", config.POPULATION_SIZE))
        print(f"[*] Population loaded: {len(pop.members)} member(s), "
              f"best_loss={pop.best().loss:.6f}.")
        return pop
    except Exception as e:
        print(f"[!] Failed to load population ({e}). Starting fresh.")
        return None
