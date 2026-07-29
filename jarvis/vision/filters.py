"""One Euro Filter (Casiez et al. 2012) — the spec-mandated smoother for
landmark→cursor mapping. A naive moving average adds lag; One Euro adapts its
cutoff to speed: smooth when slow, responsive when fast.
"""
from __future__ import annotations

import math


class LowPass:
    def __init__(self) -> None:
        self._y: float | None = None

    def apply(self, x: float, alpha: float) -> float:
        if self._y is None:
            self._y = x
        else:
            self._y = alpha * x + (1.0 - alpha) * self._y
        return self._y

    @property
    def last(self) -> float | None:
        return self._y


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007,
                 d_cutoff: float = 1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x = LowPass()
        self._dx = LowPass()
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._t_prev = t
            self._dx.apply(0.0, 1.0)
            return self._x.apply(x, 1.0)
        dt = max(1e-6, t - self._t_prev)
        self._t_prev = t

        prev = self._x.last if self._x.last is not None else x
        dx = (x - prev) / dt
        edx = self._dx.apply(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x.apply(x, self._alpha(cutoff, dt))

    def reset(self) -> None:
        self._x = LowPass()
        self._dx = LowPass()
        self._t_prev = None


class PointFilter:
    """One Euro on an (x, y) pair."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007,
                 d_cutoff: float = 1.0):
        self.fx = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self.fy = OneEuroFilter(min_cutoff, beta, d_cutoff)

    def filter(self, x: float, y: float, t: float) -> tuple[float, float]:
        return self.fx.filter(x, t), self.fy.filter(y, t)

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()
