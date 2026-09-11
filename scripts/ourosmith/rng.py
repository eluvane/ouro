"""Deterministic pseudo-random source (SplitMix64).

The standard library's ``random`` module is deliberately not used: its
distribution helpers have changed between Python releases, and a persisted seed
must replay the same program forever.  Sub-streams are derived by label so that
adding a generator choice in one place does not shift every later choice.
"""
from __future__ import annotations

import hashlib
from typing import Sequence, TypeVar

T = TypeVar("T")
_MASK = (1 << 64) - 1


def _mix(z: int) -> int:
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & _MASK
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & _MASK
    return z ^ (z >> 31)


class Rng:
    """SplitMix64 stream with convenience helpers over sequences."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK
        return _mix(self._state)

    def derive(self, label: str) -> "Rng":
        digest = hashlib.sha256(f"{self._state:016x}:{label}".encode()).digest()
        return Rng(int.from_bytes(digest[:8], "big"))

    def below(self, n: int) -> int:
        if n <= 0:
            raise ValueError("below requires a positive bound")
        return self.next_u64() % n

    def between(self, lo: int, hi: int) -> int:
        """Uniform integer in the inclusive range [lo, hi]."""
        return lo + self.below(hi - lo + 1)

    def chance(self, numerator: int, denominator: int) -> bool:
        return self.below(denominator) < numerator

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("choice from an empty sequence")
        return items[self.below(len(items))]

    def weighted(self, table: Sequence[tuple[int, T]]) -> T:
        total = sum(weight for weight, _ in table if weight > 0)
        if total <= 0:
            raise ValueError("weighted choice needs a positive total weight")
        pick = self.below(total)
        for weight, item in table:
            if weight <= 0:
                continue
            if pick < weight:
                return item
            pick -= weight
        raise AssertionError("unreachable weighted choice")

    def shuffled(self, items: Sequence[T]) -> list[T]:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out

    def sample(self, items: Sequence[T], k: int) -> list[T]:
        return self.shuffled(items)[: max(0, min(k, len(items)))]
