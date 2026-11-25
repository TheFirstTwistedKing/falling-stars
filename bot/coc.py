"""CoC식 d100 백분율 판정 규칙."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import IntEnum

from .dice import parse_and_roll

# 능력치: (표시 이름, 생성 식, 배수)
STATS: dict[str, tuple[str, int]] = {
    "근력": ("3d6", 5),
    "건강": ("3d6", 5),
    "크기": ("2d6+6", 5),
    "민첩": ("3d6", 5),
    "외모": ("3d6", 5),
    "지능": ("2d6+6", 5),
    "정신": ("3d6", 5),
    "교육": ("2d6+6", 5),
}
RESOURCES = ("체력", "마력", "이성", "행운")


class Level(IntEnum):
    FUMBLE = -1
    FAIL = 0
    REGULAR = 1
    HARD = 2
    EXTREME = 3
    CRITICAL = 4


LEVEL_NAMES = {
    Level.FUMBLE: "대실패",
    Level.FAIL: "실패",
    Level.REGULAR: "성공",
    Level.HARD: "어려운 성공",
    Level.EXTREME: "극단적 성공",
    Level.CRITICAL: "대성공",
}

DIFFICULTY = {"보통": Level.REGULAR, "어려움": Level.HARD, "극단": Level.EXTREME}


@dataclass
class D100Roll:
    value: int
    tens_rolled: list[int]
    units: int
    bonus: int  # 양수면 보너스, 음수면 페널티 주사위 개수


def roll_d100(bonus: int = 0, penalty: int = 0, rng: random.Random | None = None) -> D100Roll:
    """보너스/페널티 주사위는 서로 상쇄된다. 십의 자리만 추가로 굴린다."""
    rng = rng or random.Random()
    net = bonus - penalty
    units = rng.randint(0, 9)
    tens = [rng.randint(0, 9) for _ in range(1 + abs(net))]

    def combine(t: int) -> int:
        v = t * 10 + units
        return 100 if v == 0 else v

    candidates = [combine(t) for t in tens]
    if net > 0:
        value = min(candidates)
    elif net < 0:
        value = max(candidates)
    else:
        value = candidates[0]
    return D100Roll(value=value, tens_rolled=tens, units=units, bonus=net)


def judge(roll: int, skill: int) -> Level:
    if roll == 1:
        return Level.CRITICAL
    fumble_from = 100 if skill >= 50 else 96
    if roll >= fumble_from:
        return Level.FUMBLE
    if roll <= skill // 5:
        return Level.EXTREME
    if roll <= skill // 2:
        return Level.HARD
    if roll <= skill:
        return Level.REGULAR
    return Level.FAIL


def passed(level: Level, difficulty: str = "보통") -> bool:
    return level >= DIFFICULTY[difficulty]


def generate_stats(rng: random.Random | None = None) -> dict[str, int]:
    rng = rng or random.Random()
    return {name: parse_and_roll(expr, rng).total * mult for name, (expr, mult) in STATS.items()}


def derive_resources(stats: dict[str, int], luck: int) -> dict[str, dict[str, int]]:
    hp = (stats.get("건강", 0) + stats.get("크기", 0)) // 10
    mp = stats.get("정신", 0) // 5
    san = stats.get("정신", 0)
    return {
        "체력": {"cur": hp, "max": hp},
        "마력": {"cur": mp, "max": mp},
        "이성": {"cur": san, "max": 99},
        "행운": {"cur": luck, "max": 99},
    }


@dataclass
class SanityResult:
    roll: D100Roll
    level: Level
    loss: int
    loss_detail: str


def sanity_check(current_san: int, success_loss: str, fail_loss: str,
                 rng: random.Random | None = None) -> SanityResult:
    """이성 판정. 성공 시 success_loss, 실패 시 fail_loss. 대실패는 실패 손실 최댓값."""
    rng = rng or random.Random()
    r = roll_d100(rng=rng)
    level = judge(r.value, current_san)
    if level == Level.FUMBLE:
        res = parse_and_roll(fail_loss, rng)
        loss = sum(t.sign * (len(t.kept_idx) * _sides(t.label) if t.rolls else t.value)
                   for t in res.terms)
        detail = f"{fail_loss} 최댓값"
    else:
        expr = success_loss if level >= Level.REGULAR else fail_loss
        res = parse_and_roll(expr, rng)
        loss = res.total
        detail = f"{expr} → {res.breakdown()}"
    return SanityResult(roll=r, level=level, loss=max(0, loss), loss_detail=detail)


def _sides(label: str) -> int:
    after_d = label.split("d", 1)[1]
    digits = ""
    for ch in after_d:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits)
