"""임베드 스타일.

방향: 깊은 밤하늘(남색) 위로 떨어지는 불씨 하나(호박색).
색은 밤색 하나를 기본으로 두고, 결과의 무게에 따라 불씨의 밝기만 바꾼다.
"""
from __future__ import annotations

import discord

from .coc import Level

NIGHT = discord.Colour(0x141B2D)      # 기본: 서술, 정보
EMBER = discord.Colour(0xE8A33D)      # 성공
FLARE = discord.Colour(0xFFD27A)      # 대성공 / 극단적 성공
ASH = discord.Colour(0x3B4458)        # 실패
CINDER = discord.Colour(0x9E3B2F)     # 대실패, 경고

LEVEL_COLOUR = {
    Level.CRITICAL: FLARE,
    Level.EXTREME: FLARE,
    Level.HARD: EMBER,
    Level.REGULAR: EMBER,
    Level.FAIL: ASH,
    Level.FUMBLE: CINDER,
}


def embed(title: str | None = None, description: str | None = None,
          colour: discord.Colour = NIGHT) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=colour)


def error(message: str) -> discord.Embed:
    return discord.Embed(description=message, colour=CINDER)


def bar(cur: int, maximum: int, width: int = 12) -> str:
    """자원 게이지. 채워진 칸 = 남은 빛."""
    if maximum <= 0:
        return "─" * width
    filled = max(0, min(width, round(width * cur / maximum)))
    return "█" * filled + "░" * (width - filled)
