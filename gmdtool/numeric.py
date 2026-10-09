from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Callable


@dataclass(frozen=True, eq=False)
class GDReal:
    """Finite GD decimal token with exact numeric semantics.

    ``raw`` preserves the original spelling. Arithmetic is performed as an exact
    rational and only succeeds when the result has a finite decimal expansion.
    Python ``float`` is deliberately rejected to avoid accidental binary-rounding
    noise in level data.
    """

    raw: str

    def __post_init__(self) -> None:
        if not isinstance(self.raw, str):
            raise TypeError("GDReal raw value must be str")
        try:
            value = Decimal(self.raw)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid GD real token: {self.raw!r}") from exc
        if not value.is_finite():
            raise ValueError(f"GD real values must be finite: {self.raw!r}")

    @property
    def decimal(self) -> Decimal:
        return Decimal(self.raw)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.decimal)

    @property
    def is_integer(self) -> bool:
        return self.decimal == self.decimal.to_integral_value()

    @classmethod
    def from_value(cls, value: Any) -> "GDReal":
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise TypeError("bool is not accepted as a GD real")
        if isinstance(value, float):
            raise TypeError(
                "Python float is intentionally rejected for GD real values; "
                "use str, Decimal, int, or GDReal"
            )
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("GD real values must be finite")
            return cls(format(value, "f"))
        if isinstance(value, int):
            return cls(str(value))
        if isinstance(value, str):
            return cls(value)
        raise TypeError(f"Cannot convert {type(value).__name__} to GDReal")

    @staticmethod
    def _from_fraction(value: Fraction) -> "GDReal":
        denominator = value.denominator
        twos = fives = 0
        while denominator % 2 == 0:
            denominator //= 2
            twos += 1
        while denominator % 5 == 0:
            denominator //= 5
            fives += 1
        if denominator != 1:
            raise ArithmeticError(
                "GDReal cannot exactly represent a non-terminating decimal result"
            )

        places = max(twos, fives)
        scaled = value.numerator * (2 ** (places - twos)) * (5 ** (places - fives))
        sign = "-" if scaled < 0 else ""
        digits = str(abs(scaled))
        if places:
            digits = digits.rjust(places + 1, "0")
            raw = f"{sign}{digits[:-places]}.{digits[-places:]}"
        else:
            raw = f"{sign}{digits}"
        return GDReal(raw)

    def to_integer_exact(self) -> int:
        if not self.is_integer:
            raise ArithmeticError(f"{self.raw!r} is not an integer")
        return int(self.decimal)

    def __str__(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return f"GDReal({self.raw!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return False
        try:
            return self.decimal == GDReal.from_value(other).decimal
        except (TypeError, ValueError):
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self.decimal)

    def _binary(self, other: Any, op: Callable[[Fraction, Fraction], Fraction]) -> "GDReal":
        return self._from_fraction(op(self.fraction, GDReal.from_value(other).fraction))

    def __add__(self, other: Any) -> "GDReal":
        return self._binary(other, lambda a, b: a + b)

    def __radd__(self, other: Any) -> "GDReal":
        return GDReal.from_value(other) + self

    def __sub__(self, other: Any) -> "GDReal":
        return self._binary(other, lambda a, b: a - b)

    def __rsub__(self, other: Any) -> "GDReal":
        return GDReal.from_value(other) - self

    def __mul__(self, other: Any) -> "GDReal":
        return self._binary(other, lambda a, b: a * b)

    def __rmul__(self, other: Any) -> "GDReal":
        return GDReal.from_value(other) * self

    def __truediv__(self, other: Any) -> "GDReal":
        return self._binary(other, lambda a, b: a / b)

    def __neg__(self) -> "GDReal":
        return self._from_fraction(-self.fraction)

    def _cmp(self, other: Any) -> Decimal:
        return GDReal.from_value(other).decimal

    def __lt__(self, other: Any) -> bool:
        return self.decimal < self._cmp(other)

    def __le__(self, other: Any) -> bool:
        return self.decimal <= self._cmp(other)

    def __gt__(self, other: Any) -> bool:
        return self.decimal > self._cmp(other)

    def __ge__(self, other: Any) -> bool:
        return self.decimal >= self._cmp(other)
