"""주사위 표기 파서. eval 없이 정규식으로만 해석한다.

지원 표기: 2d6, d100, 3d6+2, 4d6kh3(높은 3개), 2d20kl1(낮은 1개), 1d8+1d6-1
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

MAX_DICE = 100
MAX_SIDES = 1000
MAX_TERMS = 20

_TERM = re.compile(r"([+-])?(?:(\d*)[dD](\d+)(?:(kh|kl)(\d+))?|(\d+))")


class DiceError(ValueError):
    pass


@dataclass
class TermResult:
    sign: int
    label: str
    rolls: list[int] = field(default_factory=list)
    kept_idx: set[int] = field(default_factory=set)
    value: int = 0


@dataclass
class RollResult:
    expression: str
    terms: list[TermResult]

    @property
    def total(self) -> int:
        return sum(t.sign * t.value for t in self.terms)

    def breakdown(self) -> str:
        parts = []
        for i, t in enumerate(self.terms):
            sign = "- " if t.sign < 0 else ("+ " if i else "")
            if t.rolls:
                shown = ", ".join(
                    str(r) if j in t.kept_idx else f"~~{r}~~" for j, r in enumerate(t.rolls)
                )
                parts.append(f"{sign}{t.label} [{shown}]")
            else:
                parts.append(f"{sign}{t.value}")
        return " ".join(parts)


def parse_and_roll(expression: str, rng: random.Random | None = None) -> RollResult:
    rng = rng or random.Random()
    expr = re.sub(r"\s*([+-])\s*", r"\1", expression.strip())
    if not expr:
        raise DiceError("주사위 식이 비어 있습니다.")
    if re.search(r"\s", expr):
        raise DiceError("항 사이에는 + 또는 - 가 필요합니다. (예: 2d6+3)")

    pos = 0
    terms: list[TermResult] = []
    while pos < len(expr):
        m = _TERM.match(expr, pos)
        if not m or m.end() == pos:
            raise DiceError(f"'{expr[pos:]}' 부분을 해석할 수 없습니다.")
        if terms and m.group(1) is None:
            raise DiceError("항 사이에는 + 또는 - 가 필요합니다.")
        sign = -1 if m.group(1) == "-" else 1
        if m.group(6) is not None:
            n = int(m.group(6))
            terms.append(TermResult(sign=sign, label=str(n), value=n))
        else:
            count = int(m.group(2)) if m.group(2) else 1
            sides = int(m.group(3))
            if not 1 <= count <= MAX_DICE:
                raise DiceError(f"주사위 개수는 1~{MAX_DICE}개입니다.")
            if not 2 <= sides <= MAX_SIDES:
                raise DiceError(f"주사위 면 수는 2~{MAX_SIDES}입니다.")
            rolls = [rng.randint(1, sides) for _ in range(count)]
            kept_idx = set(range(count))
            label = f"{count}d{sides}"
            if m.group(4):
                k = int(m.group(5))
                if not 1 <= k <= count:
                    raise DiceError("남길 주사위 수는 1 이상, 굴린 개수 이하여야 합니다.")
                order = sorted(range(count), key=lambda j: rolls[j], reverse=(m.group(4) == "kh"))
                kept_idx = set(order[:k])
                label += f"{m.group(4)}{k}"
            value = sum(rolls[j] for j in kept_idx)
            terms.append(TermResult(sign, label, rolls, kept_idx, value))
        if len(terms) > MAX_TERMS:
            raise DiceError(f"항은 최대 {MAX_TERMS}개입니다.")
        pos = m.end()
    return RollResult(expression=expr, terms=terms)
