"""임베드 스타일.

방향: 맑은 하늘색을 기본으로, 결과가 좋을수록 연노란 빛이 밝아진다.
나쁜 결과는 노란빛 없이 하늘색이 흐려지거나 깊어지는 것으로만 표현한다.
"""
from __future__ import annotations

import discord

from .coc import Level

SKY = discord.Colour(0x8ECAE6)        # 기본: 서술, 정보 (하늘색)
LEMON = discord.Colour(0xFFE48A)      # 성공 (연노란색)
SUNLIGHT = discord.Colour(0xFFD45C)   # 대성공 / 극단적 성공 (더 진한 연노랑, 가장 눈에 띄게)
HAZE = discord.Colour(0x7A9BB5)       # 실패 (흐린 하늘)
DEEP = discord.Colour(0x3A6E99)       # 대실패, 경고 (깊은 하늘)

LEVEL_COLOUR = {
    Level.CRITICAL: SUNLIGHT,
    Level.EXTREME: SUNLIGHT,
    Level.HARD: LEMON,
    Level.REGULAR: LEMON,
    Level.FAIL: HAZE,
    Level.FUMBLE: DEEP,
}


def embed(title: str | None = None, description: str | None = None,
          colour: discord.Colour = SKY) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=colour)


def error(message: str) -> discord.Embed:
    return discord.Embed(description=message, colour=DEEP)


def bar(cur: int, maximum: int, width: int = 12) -> str:
    """자원 게이지. 채워진 칸 = 남은 빛."""
    if maximum <= 0:
        return "─" * width
    filled = max(0, min(width, round(width * cur / maximum)))
    return "█" * filled + "░" * (width - filled)
