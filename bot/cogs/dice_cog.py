"""/roll, /판정, /이성판정"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import coc, style
from ..dice import DiceError, parse_and_roll
from ..helpers import session_log


def lookup_value(char: dict, name: str) -> int | None:
    if name in char["stats"]:
        return int(char["stats"][name])
    if name in char["skills"]:
        return int(char["skills"][name])
    if name in char["resources"]:
        return int(char["resources"][name]["cur"])
    return None


class DiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll", description="주사위를 굴립니다. 예: 2d6+3, d100, 4d6kh3")
    @app_commands.describe(식="주사위 식", 이유="무엇을 위해 굴리는지", 비공개="나만 보기")
    async def roll(self, interaction: discord.Interaction, 식: str, 이유: str | None = None,
                   비공개: bool = False):
        try:
            result = parse_and_roll(식)
        except DiceError as e:
            await interaction.response.send_message(embed=style.error(str(e)), ephemeral=True)
            return
        e = style.embed(title=f"{result.total}", description=result.breakdown()[:4000])
        e.set_author(name=f"{interaction.user.display_name} · {result.expression}")
        if 이유:
            e.add_field(name="이유", value=이유[:1024], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=비공개)
        if not 비공개:
            await session_log(interaction, "roll", interaction.user.display_name,
                              f"{result.expression} = {result.total} {이유 or ''}".strip())

    async def _skill_autocomplete(self, interaction: discord.Interaction, current: str):
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        if not char:
            return []
        names = list(char["skills"]) + list(char["stats"]) + list(char["resources"])
        return [app_commands.Choice(name=f"{n} ({lookup_value(char, n)})", value=n)
                for n in names if current in n][:25]

    @app_commands.command(name="판정", description="d100 판정. 현재 캐릭터의 기능·능력치나 직접 입력한 수치로 판정합니다.")
    @app_commands.describe(기능="캐릭터의 기능·능력치 이름", 수치="직접 입력하는 목표값 (기능보다 우선)",
                           보너스="보너스 주사위 개수", 페널티="페널티 주사위 개수",
                           난이도="필요한 성공 등급", 비공개="나만 보기")
    @app_commands.autocomplete(기능=_skill_autocomplete)
    @app_commands.choices(난이도=[app_commands.Choice(name=k, value=k) for k in coc.DIFFICULTY])
    async def check(self, interaction: discord.Interaction, 기능: str | None = None,
                    수치: app_commands.Range[int, 1, 200] | None = None,
                    보너스: app_commands.Range[int, 0, 2] = 0, 페널티: app_commands.Range[int, 0, 2] = 0,
                    난이도: str = "보통", 비공개: bool = False):
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        label = 기능 or "판정"
        target = 수치
        if target is None:
            if not 기능:
                await interaction.response.send_message(
                    embed=style.error("기능 이름이나 수치 중 하나는 입력해야 합니다."), ephemeral=True)
                return
            if not char:
                await interaction.response.send_message(
                    embed=style.error("선택된 캐릭터가 없습니다. `/캐릭터 선택`을 하거나 수치를 직접 입력하세요."),
                    ephemeral=True)
                return
            target = lookup_value(char, 기능)
            if target is None:
                await interaction.response.send_message(
                    embed=style.error(f"'{char['name']}'에게 '{기능}' 항목이 없습니다."), ephemeral=True)
                return

        r = coc.roll_d100(보너스, 페널티)
        level = coc.judge(r.value, target)
        ok = coc.passed(level, 난이도)
        verdict = coc.LEVEL_NAMES[level]
        if level >= coc.Level.REGULAR and not ok:
            verdict += f" · {난이도} 난이도 미달"
        colour = style.LEVEL_COLOUR[level] if (ok or level <= coc.Level.FAIL) else style.HAZE

        use_char = char is not None and 수치 is None
        who = char["name"] if use_char else interaction.user.display_name
        e = style.embed(title=verdict, colour=colour)
        e.set_author(name=f"{who} · {label} {target}")
        e.add_field(name="굴림", value=f"**{r.value}**", inline=True)
        e.add_field(name="어려움 / 극단", value=f"{target // 2} / {target // 5}", inline=True)
        if r.bonus:
            kind = "보너스" if r.bonus > 0 else "페널티"
            tens = ", ".join(str(t * 10) for t in r.tens_rolled)
            e.add_field(name=f"{kind} 주사위", value=f"십의 자리 [{tens}] · 일의 자리 {r.units}", inline=False)
        if use_char and char["avatar_url"]:
            e.set_thumbnail(url=char["avatar_url"])
        await interaction.response.send_message(embed=e, ephemeral=비공개)
        if not 비공개:
            await session_log(interaction, "check", who, f"{label}({target}) → {r.value} {verdict}")

    @app_commands.command(name="이성판정", description="현재 캐릭터의 이성 판정. 결과만큼 이성이 자동으로 줄어듭니다.")
    @app_commands.describe(성공손실="성공 시 잃는 양 (예: 0, 1, 1d3)", 실패손실="실패 시 잃는 양 (예: 1d6)")
    async def sanity(self, interaction: discord.Interaction, 성공손실: str, 실패손실: str):
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        if not char or "이성" not in char["resources"]:
            await interaction.response.send_message(
                embed=style.error("이성 수치가 있는 캐릭터를 먼저 선택하세요."), ephemeral=True)
            return
        san = char["resources"]["이성"]
        try:
            res = coc.sanity_check(int(san["cur"]), 성공손실, 실패손실)
        except DiceError as e:
            await interaction.response.send_message(embed=style.error(str(e)), ephemeral=True)
            return
        before = int(san["cur"])
        after = max(0, before - res.loss)
        resources = dict(char["resources"])
        resources["이성"] = {"cur": after, "max": san["max"]}
        await self.bot.db.update_character(char["id"], resources=resources)

        level_name = coc.LEVEL_NAMES[res.level]
        e = style.embed(title=f"이성 {before} → {after}", colour=style.LEVEL_COLOUR[res.level])
        e.set_author(name=f"{char['name']} · 이성 판정")
        e.add_field(name="굴림", value=f"**{res.roll.value}** · {level_name}", inline=True)
        e.add_field(name="손실", value=f"{res.loss} ({res.loss_detail})"[:1024], inline=True)
        e.add_field(name="남은 이성", value=f"`{style.bar(after, int(san['max']))}`", inline=False)
        if res.loss >= 5:
            e.set_footer(text="한 번에 5 이상 잃었습니다. GM은 일시적 광기 여부를 판단하세요.")
        await interaction.response.send_message(embed=e)
        await session_log(interaction, "sanity", char["name"],
                          f"이성판정 {res.roll.value} {level_name}, -{res.loss} ({before}→{after})")


async def setup(bot):
    await bot.add_cog(DiceCog(bot))
