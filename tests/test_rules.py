import random

import pytest

from bot import coc
from bot.dice import DiceError, parse_and_roll
from bot.cogs.story import reveal_steps


def test_basic_expression_bounds():
    rng = random.Random(1)
    for _ in range(500):
        r = parse_and_roll("2d6+3", rng)
        assert 5 <= r.total <= 15


def test_keep_highest():
    class Fixed(random.Random):
        seq = iter([1, 6, 3, 5])
        def randint(self, a, b):
            return next(self.seq)
    r = parse_and_roll("4d6kh3", Fixed())
    assert r.total == 14
    assert "~~1~~" in r.breakdown()


def test_negative_and_constant():
    for seed in range(50):
        r = parse_and_roll("10 - 1d2", random.Random(seed))
        assert r.total in (8, 9)


@pytest.mark.parametrize("bad", ["", "abc", "2d", "1d1", "101d6", "2d6 3", "4d6kh5", "1d6**2"])
def test_bad_expressions(bad):
    with pytest.raises(DiceError):
        parse_and_roll(bad)


@pytest.mark.parametrize("roll,skill,level", [
    (1, 10, coc.Level.CRITICAL),
    (100, 80, coc.Level.FUMBLE),
    (99, 80, coc.Level.FAIL),
    (96, 40, coc.Level.FUMBLE),
    (95, 40, coc.Level.FAIL),
    (12, 60, coc.Level.EXTREME),
    (13, 60, coc.Level.HARD),
    (30, 60, coc.Level.HARD),
    (31, 60, coc.Level.REGULAR),
    (60, 60, coc.Level.REGULAR),
    (61, 60, coc.Level.FAIL),
])
def test_judge(roll, skill, level):
    assert coc.judge(roll, skill) == level


def test_difficulty():
    assert coc.passed(coc.Level.HARD, "어려움")
    assert not coc.passed(coc.Level.REGULAR, "어려움")
    assert not coc.passed(coc.Level.HARD, "극단")


def test_d100_range_and_bonus_penalty():
    rng = random.Random(5)
    for _ in range(2000):
        assert 1 <= coc.roll_d100(rng=rng).value <= 100
    # 보너스는 후보 중 최솟값, 페널티는 최댓값
    for _ in range(500):
        b = coc.roll_d100(bonus=2, rng=rng)
        cands = [100 if t * 10 + b.units == 0 else t * 10 + b.units for t in b.tens_rolled]
        assert b.value == min(cands) and len(b.tens_rolled) == 3
        p = coc.roll_d100(penalty=1, rng=rng)
        cands = [100 if t * 10 + p.units == 0 else t * 10 + p.units for t in p.tens_rolled]
        assert p.value == max(cands)
    assert len(coc.roll_d100(bonus=1, penalty=1, rng=rng).tens_rolled) == 1


def test_stats_and_resources():
    rng = random.Random(3)
    for _ in range(300):
        s = coc.generate_stats(rng)
        assert 15 <= s["근력"] <= 90 and s["근력"] % 5 == 0
        assert 40 <= s["크기"] <= 90
    res = coc.derive_resources({"건강": 50, "크기": 65, "정신": 60}, 45)
    assert res["체력"] == {"cur": 11, "max": 11}
    assert res["마력"]["max"] == 12
    assert res["이성"]["cur"] == 60
    assert res["행운"]["cur"] == 45


def test_sanity_fumble_takes_max():
    class Fumble(random.Random):
        def randint(self, a, b):
            return 9 if (a, b) == (0, 9) else b  # 99 → san 30에서 대실패
    r = coc.sanity_check(30, "1", "1d6+1", Fumble())
    assert r.roll.value == 99 and r.level == coc.Level.FUMBLE and r.loss == 7


def test_sanity_success_uses_success_loss():
    class Five(random.Random):
        calls = 0
        def randint(self, a, b):
            if (a, b) == (0, 9):
                self.calls += 1
                return 5 if self.calls == 1 else 0  # units 5, tens 0 → 5
            return 1
    r = coc.sanity_check(50, "0", "1d6", Five())
    assert r.roll.value == 5 and r.loss == 0


def test_reveal_steps_monotonic():
    text = "어둠이 내려앉은 거리 위로 작은 빛 하나가 천천히 떨어진다. " * 5
    steps = reveal_steps(text)
    assert steps[-1] == text
    assert 2 <= len(steps) <= 8
    for a, b in zip(steps, steps[1:]):
        assert b.startswith(a) and len(b) > len(a)
    assert reveal_steps("짧다") == ["짧다"]
