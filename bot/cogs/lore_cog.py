"""/도감 ... 세계관 도감"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import config, style
from ..helpers import is_gm
from ..lore import LoreEntry, load_static, search


def entry_embed(e: LoreEntry) -> discord.Embed:
    em = style.embed(title=e.name, description=e.body[:4000] or "내용이 없습니다.")
    em.set_author(name=e.category)
    if e.tags:
        em.add_field(name="검색어", value=", ".join(e.tags)[:1024])
    em.set_footer(text=e.source)
    return em


class LoreModal(discord.ui.Modal, title="도감 항목"):
    category = discord.ui.TextInput(label="분류", max_length=40)
    name = discord.ui.TextInput(label="이름", max_length=80)
    tags = discord.ui.TextInput(label="검색어 (쉼표로 구분, 선택)", required=False, max_length=200)
    body = discord.ui.TextInput(label="설명", style=discord.TextStyle.paragraph, max_length=4000)

    def __init__(self, cog: "LoreCog", entry: LoreEntry | None = None):
        super().__init__()
        self.cog = cog
        if entry:
            self.category.default = entry.category
            self.name.default = entry.name
            self.tags.default = ", ".join(entry.tags)
            self.body.default = entry.body

    async def on_submit(self, interaction: discord.Interaction):
        tags = [t.strip() for t in self.tags.value.split(",") if t.strip()]
        entry = LoreEntry(category=self.category.value.strip(), name=self.name.value.strip(),
                          body=self.body.value, tags=tags, source="서버 도감")
        await self.cog.bot.db.upsert_lore(interaction.guild_id, entry.category, entry.name,
                                          entry.body, entry.tags, interaction.user.id)
        await interaction.response.send_message(content="도감에 저장했습니다.", embed=entry_embed(entry))


def _from_row(row: dict) -> LoreEntry:
    return LoreEntry(category=row["category"], name=row["name"], body=row["body"],
                     tags=list(row.get("tags") or []), source="서버 도감")


class LoreCog(commands.GroupCog, group_name="도감", group_description="세계관 도감"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def entries(self, guild_id: int) -> list[LoreEntry]:
        static = load_static(config.LORE_PATH)
        dynamic = [_from_row(r) for r in await self.bot.db.list_lore(guild_id)]
        names = {e.name for e in dynamic}
        return dynamic + [e for e in static if e.name not in names]

    async def _name_ac(self, interaction: discord.Interaction, current: str):
        entries = await self.entries(interaction.guild_id)
        hits = search(entries, current) if current else entries
        return [app_commands.Choice(name=f"{e.name} · {e.category}"[:100], value=e.name) for e in hits][:25]

    async def _category_ac(self, interaction: discord.Interaction, current: str):
        cats = sorted({e.category for e in await self.entries(interaction.guild_id)})
        return [app_commands.Choice(name=c, value=c) for c in cats if current in c][:25]

    @app_commands.command(name="검색", description="도감에서 이름·검색어·내용으로 찾습니다.")
    @app_commands.autocomplete(키워드=_name_ac)
    async def find(self, interaction: discord.Interaction, 키워드: str):
        hits = search(await self.entries(interaction.guild_id), 키워드)
        if not hits:
            await interaction.response.send_message(embed=style.embed(description="찾는 항목이 없습니다."),
                                                    ephemeral=True)
            return
        em = entry_embed(hits[0])
        if len(hits) > 1:
            em.add_field(name="비슷한 항목", value=", ".join(h.name for h in hits[1:11])[:1024], inline=False)
        await interaction.response.send_message(embed=em)

    @app_commands.command(name="목록", description="도감 항목을 분류별로 봅니다.")
    @app_commands.autocomplete(분류=_category_ac)
    async def list_(self, interaction: discord.Interaction, 분류: str | None = None):
        entries = await self.entries(interaction.guild_id)
        if 분류:
            entries = [e for e in entries if e.category == 분류]
        if not entries:
            await interaction.response.send_message(
                embed=style.embed(description="도감이 비어 있습니다. GM이 `/도감 추가`로 채울 수 있습니다."),
                ephemeral=True)
            return
        grouped: dict[str, list[str]] = {}
        for e in entries:
            grouped.setdefault(e.category, []).append(e.name)
        em = style.embed(title="도감")
        for cat, names in list(grouped.items())[:25]:
            em.add_field(name=f"{cat} · {len(names)}", value=", ".join(sorted(names))[:1024], inline=False)
        await interaction.response.send_message(embed=em)

    @app_commands.command(name="추가", description="도감 항목을 추가하거나 고칩니다. (GM)")
    @app_commands.autocomplete(기존항목=_name_ac)
    @app_commands.describe(기존항목="고칠 항목 이름 (비우면 새로 추가)")
    async def add(self, interaction: discord.Interaction, 기존항목: str | None = None):
        if not await is_gm(interaction):
            await interaction.response.send_message(embed=style.error("GM만 도감을 고칠 수 있습니다."), ephemeral=True)
            return
        entry = None
        if 기존항목:
            hits = [e for e in await self.entries(interaction.guild_id) if e.name == 기존항목]
            entry = hits[0] if hits else None
        await interaction.response.send_modal(LoreModal(self, entry))

    @app_commands.command(name="삭제", description="서버 도감 항목을 지웁니다. (GM, 설정집 파일 항목은 제외)")
    @app_commands.autocomplete(이름=_name_ac)
    async def delete(self, interaction: discord.Interaction, 이름: str):
        if not await is_gm(interaction):
            await interaction.response.send_message(embed=style.error("GM만 도감을 고칠 수 있습니다."), ephemeral=True)
            return
        n = await self.bot.db.delete_lore(interaction.guild_id, 이름)
        msg = f"'{이름}'을(를) 지웠습니다." if n else "서버 도감에 그 항목이 없습니다. (설정집 파일 항목은 파일에서 지워야 합니다)"
        await interaction.response.send_message(embed=style.embed(description=msg), ephemeral=True)


async def setup(bot):
    await bot.add_cog(LoreCog(bot))
