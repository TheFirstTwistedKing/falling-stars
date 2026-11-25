"""/캐릭터 ... 캐릭터 시트"""
from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from .. import coc, style
from ..helpers import session_log


def sheet_embed(char: dict, owner: discord.abc.User | None = None) -> discord.Embed:
    e = style.embed(title=char["name"], description=char["notes"][:1000] or None)
    if owner:
        e.set_author(name=owner.display_name, icon_url=owner.display_avatar.url)
    if char["avatar_url"]:
        e.set_thumbnail(url=char["avatar_url"])

    res_lines = []
    for key in coc.RESOURCES:
        if key in char["resources"]:
            r = char["resources"][key]
            res_lines.append(f"`{key}` `{style.bar(int(r['cur']), int(r['max']), 10)}` {r['cur']}/{r['max']}")
    if res_lines:
        e.add_field(name="자원", value="\n".join(res_lines), inline=False)

    stats = list(char["stats"].items())
    if stats:
        half = (len(stats) + 1) // 2
        for i, chunk in enumerate((stats[:half], stats[half:])):
            e.add_field(name="능력치 · 어려움 · 극단" if i == 0 else "​",
                        value="\n".join(f"`{k}` **{v}** · {v // 2} · {v // 5}" for k, v in chunk) or "​",
                        inline=True)
    skills = sorted(char["skills"].items(), key=lambda kv: -int(kv[1]))
    if skills:
        text = "  ".join(f"`{k}` {v}" for k, v in skills)
        e.add_field(name="기능", value=text[:1024], inline=False)
    return e


class CharacterCog(commands.GroupCog, group_name="캐릭터", group_description="캐릭터 시트"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def _active_or_error(self, interaction: discord.Interaction) -> dict | None:
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        if not char:
            await interaction.response.send_message(
                embed=style.error("선택된 캐릭터가 없습니다. `/캐릭터 생성` 또는 `/캐릭터 선택`을 먼저 하세요."),
                ephemeral=True)
        return char

    async def _my_chars_ac(self, interaction: discord.Interaction, current: str):
        chars = await self.bot.db.list_characters(interaction.guild_id, interaction.user.id)
        return [app_commands.Choice(name=c["name"], value=c["name"]) for c in chars if current in c["name"]][:25]

    async def _skill_ac(self, interaction: discord.Interaction, current: str):
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        if not char:
            return []
        return [app_commands.Choice(name=k, value=k) for k in char["skills"] if current in k][:25]

    @app_commands.command(name="생성", description="새 캐릭터를 만듭니다. 만든 캐릭터가 바로 선택됩니다.")
    @app_commands.describe(이름="캐릭터 이름", 방식="랜덤: 능력치를 주사위로 / 직접: 0에서 시작해 직접 입력")
    @app_commands.choices(방식=[app_commands.Choice(name="랜덤", value="랜덤"),
                              app_commands.Choice(name="직접", value="직접")])
    async def create(self, interaction: discord.Interaction, 이름: app_commands.Range[str, 1, 40],
                     방식: str = "랜덤"):
        if await self.bot.db.find_character(interaction.guild_id, interaction.user.id, 이름):
            await interaction.response.send_message(embed=style.error("같은 이름의 캐릭터가 이미 있습니다."),
                                                    ephemeral=True)
            return
        if 방식 == "랜덤":
            rng = random.Random()
            stats = coc.generate_stats(rng)
            luck = sum(rng.randint(1, 6) for _ in range(3)) * 5
        else:
            stats = {k: 0 for k in coc.STATS}
            luck = 0
        resources = coc.derive_resources(stats, luck)
        cid = await self.bot.db.create_character(interaction.guild_id, interaction.user.id, 이름,
                                                 stats, resources)
        char = await self.bot.db.get_character(cid)
        await interaction.response.send_message(
            content="캐릭터를 만들고 선택했습니다." if 방식 == "랜덤" else
            "캐릭터를 만들었습니다. `/캐릭터 능력치`로 수치를 입력하세요.",
            embed=sheet_embed(char, interaction.user))

    @app_commands.command(name="보기", description="캐릭터 시트를 봅니다.")
    @app_commands.describe(이름="비우면 현재 선택된 캐릭터", 유저="다른 사람의 캐릭터를 볼 때")
    async def view(self, interaction: discord.Interaction, 이름: str | None = None,
                   유저: discord.Member | None = None):
        target = 유저 or interaction.user
        if 이름:
            char = await self.bot.db.find_character(interaction.guild_id, target.id, 이름)
        else:
            char = await self.bot.db.get_active(interaction.guild_id, target.id)
        if not char:
            await interaction.response.send_message(embed=style.error("캐릭터를 찾지 못했습니다."), ephemeral=True)
            return
        await interaction.response.send_message(embed=sheet_embed(char, target))

    @app_commands.command(name="목록", description="캐릭터 목록을 봅니다.")
    @app_commands.describe(유저="비우면 이 서버의 모든 캐릭터")
    async def list_(self, interaction: discord.Interaction, 유저: discord.Member | None = None):
        chars = await self.bot.db.list_characters(interaction.guild_id, 유저.id if 유저 else None)
        if not chars:
            await interaction.response.send_message(embed=style.embed(description="등록된 캐릭터가 없습니다."),
                                                    ephemeral=True)
            return
        lines = []
        for c in chars[:50]:
            hp = c["resources"].get("체력", {})
            san = c["resources"].get("이성", {})
            lines.append(f"**{c['name']}** · <@{c['owner_id']}> · 체력 {hp.get('cur', '-')} · 이성 {san.get('cur', '-')}")
        await interaction.response.send_message(
            embed=style.embed(title="캐릭터 목록", description="\n".join(lines)),
            allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="선택", description="판정과 상황극에 쓸 캐릭터를 고릅니다.")
    @app_commands.autocomplete(이름=_my_chars_ac)
    async def select(self, interaction: discord.Interaction, 이름: str):
        char = await self.bot.db.find_character(interaction.guild_id, interaction.user.id, 이름)
        if not char:
            await interaction.response.send_message(embed=style.error("내 캐릭터 중에 그 이름이 없습니다."),
                                                    ephemeral=True)
            return
        await self.bot.db.set_active(interaction.guild_id, interaction.user.id, char["id"])
        await interaction.response.send_message(embed=style.embed(description=f"**{이름}**을(를) 선택했습니다."),
                                                ephemeral=True)

    @app_commands.command(name="능력치", description="현재 캐릭터의 능력치를 설정합니다.")
    @app_commands.choices(항목=[app_commands.Choice(name=k, value=k) for k in coc.STATS])
    async def set_stat(self, interaction: discord.Interaction, 항목: str, 값: app_commands.Range[int, 0, 200]):
        char = await self._active_or_error(interaction)
        if not char:
            return
        stats = dict(char["stats"])
        stats[항목] = 값
        resources = dict(char["resources"])
        derived = coc.derive_resources(stats, int(resources.get("행운", {}).get("cur", 0)))
        for key in ("체력", "마력"):
            old = resources.get(key, {"cur": 0, "max": 0})
            new_max = derived[key]["max"]
            cur = new_max if int(old["cur"]) == int(old["max"]) else min(int(old["cur"]), new_max)
            resources[key] = {"cur": cur, "max": new_max}
        if 항목 == "정신" and int(resources.get("이성", {}).get("cur", 0)) == 0:
            resources["이성"] = {"cur": 값, "max": 99}
        await self.bot.db.update_character(char["id"], stats=stats, resources=resources)
        char = await self.bot.db.get_character(char["id"])
        await interaction.response.send_message(embed=sheet_embed(char, interaction.user), ephemeral=True)

    @app_commands.command(name="기능", description="현재 캐릭터의 기능 수치를 설정합니다. 값 0이면 삭제합니다.")
    @app_commands.autocomplete(이름=_skill_ac)
    async def set_skill(self, interaction: discord.Interaction, 이름: app_commands.Range[str, 1, 30],
                        값: app_commands.Range[int, 0, 200]):
        char = await self._active_or_error(interaction)
        if not char:
            return
        skills = dict(char["skills"])
        if 값 == 0:
            skills.pop(이름, None)
            msg = f"'{이름}' 기능을 지웠습니다."
        else:
            skills[이름] = 값
            msg = f"'{이름}' = {값}"
        await self.bot.db.update_character(char["id"], skills=skills)
        await interaction.response.send_message(embed=style.embed(description=msg), ephemeral=True)

    @app_commands.command(name="자원", description="체력·마력·이성·행운을 바꿉니다. 예: -3, +2, =40")
    @app_commands.choices(항목=[app_commands.Choice(name=k, value=k) for k in coc.RESOURCES])
    @app_commands.describe(변화="-3(감소), +2(증가), =40(지정)", 최대="최댓값을 바꿀 때")
    async def resource(self, interaction: discord.Interaction, 항목: str, 변화: str | None = None,
                       최대: app_commands.Range[int, 0, 999] | None = None):
        char = await self._active_or_error(interaction)
        if not char:
            return
        resources = dict(char["resources"])
        r = dict(resources.get(항목, {"cur": 0, "max": 0}))
        before = int(r["cur"])
        if 최대 is not None:
            r["max"] = 최대
        if 변화:
            v = 변화.strip().replace(" ", "")
            try:
                if v.startswith("="):
                    r["cur"] = int(v[1:])
                else:
                    r["cur"] = before + int(v)
            except ValueError:
                await interaction.response.send_message(embed=style.error("변화는 -3, +2, =40 형식으로 입력하세요."),
                                                        ephemeral=True)
                return
        r["cur"] = max(0, min(int(r["cur"]), int(r["max"]) if int(r["max"]) > 0 else int(r["cur"])))
        resources[항목] = r
        await self.bot.db.update_character(char["id"], resources=resources)
        colour = style.CINDER if r["cur"] < before else style.EMBER if r["cur"] > before else style.NIGHT
        e = style.embed(title=f"{항목} {before} → {r['cur']}", colour=colour,
                        description=f"`{style.bar(int(r['cur']), int(r['max']))}` {r['cur']}/{r['max']}")
        e.set_author(name=char["name"])
        if 항목 == "체력" and r["cur"] == 0:
            e.set_footer(text="체력이 0이 되었습니다.")
        await interaction.response.send_message(embed=e)
        await session_log(interaction, "resource", char["name"], f"{항목} {before}→{r['cur']}")

    @app_commands.command(name="꾸미기", description="현재 캐릭터의 얼굴 이미지와 소개를 정합니다.")
    @app_commands.describe(이미지="이미지 URL (상황극 말하기에도 쓰임)", 소개="시트 맨 위에 보일 짧은 소개")
    async def decorate(self, interaction: discord.Interaction, 이미지: str | None = None,
                       소개: app_commands.Range[str, 0, 1000] | None = None):
        char = await self._active_or_error(interaction)
        if not char:
            return
        fields = {}
        if 이미지 is not None:
            if 이미지 and not 이미지.startswith(("http://", "https://")):
                await interaction.response.send_message(embed=style.error("이미지는 http(s) 주소여야 합니다."),
                                                        ephemeral=True)
                return
            fields["avatar_url"] = 이미지 or None
        if 소개 is not None:
            fields["notes"] = 소개
        await self.bot.db.update_character(char["id"], **fields)
        char = await self.bot.db.get_character(char["id"])
        await interaction.response.send_message(embed=sheet_embed(char, interaction.user), ephemeral=True)

    @app_commands.command(name="삭제", description="내 캐릭터를 삭제합니다. 되돌릴 수 없습니다.")
    @app_commands.autocomplete(이름=_my_chars_ac)
    @app_commands.describe(확인="정말 지우려면 캐릭터 이름을 한 번 더 입력")
    async def delete(self, interaction: discord.Interaction, 이름: str, 확인: str):
        if 이름 != 확인:
            await interaction.response.send_message(embed=style.error("확인 칸에 캐릭터 이름을 똑같이 입력해야 합니다."),
                                                    ephemeral=True)
            return
        char = await self.bot.db.find_character(interaction.guild_id, interaction.user.id, 이름)
        if not char:
            await interaction.response.send_message(embed=style.error("캐릭터를 찾지 못했습니다."), ephemeral=True)
            return
        await self.bot.db.delete_character(char["id"])
        await interaction.response.send_message(embed=style.embed(description=f"**{이름}**을(를) 삭제했습니다."),
                                                ephemeral=True)


async def setup(bot):
    await bot.add_cog(CharacterCog(bot))
