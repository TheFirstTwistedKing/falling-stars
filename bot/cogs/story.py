"""/서술, /장면, /말하기, /npc ... 라이브 스토리 진행과 상황극"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from .. import style
from ..helpers import is_gm, send_as, session_log, webhook_for

TYPE_STEPS = 8          # 한 메시지당 최대 수정 횟수 (속도 제한에 걸려도 discord.py가 알아서 기다림)
TYPE_INTERVAL = 1.2     # 수정 간격(초)
CURSOR = " ▌"


def reveal_steps(text: str, steps: int = TYPE_STEPS) -> list[str]:
    """글자가 차례로 드러나는 중간 단계 목록. 단어 중간에서 끊지 않는다."""
    if len(text) <= 12:
        return [text]
    n = min(steps, max(2, len(text) // 30))
    cuts: list[int] = []
    for i in range(1, n):
        target = len(text) * i // n
        space = text.rfind(" ", 0, target + 1)
        newline = text.rfind("\n", 0, target + 1)
        cut = max(space, newline)
        cut = cut if cut > (cuts[-1] if cuts else 0) else target
        cuts.append(cut)
    return [text[:c].rstrip() for c in cuts] + [text]


async def typewrite(text: str, render: Callable[[str], discord.Embed],
                    first: Callable[[discord.Embed], Awaitable], edit: Callable[[discord.Embed], Awaitable]) -> None:
    parts = reveal_steps(text)
    await first(render(parts[0] + (CURSOR if len(parts) > 1 else "")))
    for i, part in enumerate(parts[1:], start=1):
        await asyncio.sleep(TYPE_INTERVAL)
        await edit(render(part + (CURSOR if i < len(parts) - 1 else "")))


class TextModal(discord.ui.Modal):
    body = discord.ui.TextInput(label="내용", style=discord.TextStyle.paragraph, max_length=4000)

    def __init__(self, title: str, callback):
        super().__init__(title=title)
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, self.body.value)


class StoryCog(commands.Cog):
    npc = app_commands.Group(name="npc", description="NPC 등록과 대사", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def _gm_only(self, interaction: discord.Interaction) -> bool:
        if await is_gm(interaction):
            return True
        await interaction.response.send_message(embed=style.error("GM만 쓸 수 있습니다."), ephemeral=True)
        return False

    # ---------- 서술 ----------
    @app_commands.command(name="서술", description="GM 서술. 내용을 비우면 여러 줄 입력창이 열립니다.")
    @app_commands.describe(내용="서술할 내용", 제목="서술 위에 붙일 짧은 제목", 타자효과="글자가 차례로 드러나게")
    @app_commands.guild_only()
    async def narrate(self, interaction: discord.Interaction, 내용: str | None = None,
                      제목: str | None = None, 타자효과: bool = True):
        if not await self._gm_only(interaction):
            return

        async def run(inter: discord.Interaction, text: str):
            def render(t: str) -> discord.Embed:
                return style.embed(title=제목, description=t or "​")

            if 타자효과:
                await typewrite(text, render,
                                lambda e: inter.response.send_message(embed=e),
                                lambda e: inter.edit_original_response(embed=e))
            else:
                await inter.response.send_message(embed=render(text))
            await session_log(inter, "narration", "GM", (f"[{제목}] " if 제목 else "") + text)

        if 내용 is None:
            await interaction.response.send_modal(TextModal("서술", run))
        else:
            await run(interaction, 내용.replace("\\n", "\n"))

    @app_commands.command(name="장면", description="장면을 전환합니다. 세션의 현재 장면으로 기록됩니다.")
    @app_commands.describe(제목="장면 이름 (장소·시간 등)", 설명="장면 묘사", 이미지="배경 이미지 URL")
    @app_commands.guild_only()
    async def scene(self, interaction: discord.Interaction, 제목: app_commands.Range[str, 1, 100],
                    설명: str | None = None, 이미지: str | None = None):
        if not await self._gm_only(interaction):
            return
        e = style.embed(title=제목, description=(설명 or "").replace("\\n", "\n")[:4000] or None,
                        colour=style.LEMON)
        e.set_author(name="장면 전환")
        if 이미지 and 이미지.startswith(("http://", "https://")):
            e.set_image(url=이미지)
        await interaction.response.send_message(embed=e)
        session = await self.bot.db.active_session(interaction.channel_id)
        if session:
            await self.bot.db.update_session(session["id"], scene=제목)
            await self.bot.db.log(session["id"], "scene", "GM", f"{제목} {설명 or ''}".strip())

    # ---------- 플레이어 상황극 ----------
    @app_commands.command(name="말하기", description="선택한 캐릭터의 이름과 얼굴로 말합니다.")
    @app_commands.describe(대사="캐릭터의 대사", 행동="대사와 함께 하는 행동 묘사")
    @app_commands.guild_only()
    async def speak(self, interaction: discord.Interaction, 대사: str | None = None, 행동: str | None = None):
        if not 대사 and not 행동:
            await interaction.response.send_message(embed=style.error("대사나 행동 중 하나는 입력하세요."), ephemeral=True)
            return
        char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
        if not char:
            await interaction.response.send_message(embed=style.error("캐릭터를 먼저 선택하세요."), ephemeral=True)
            return
        text = "\n".join(p for p in (f"*{행동}*" if 행동 else None, 대사) if p)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            await send_as(interaction.channel, char["name"], char["avatar_url"], content=text)
        except (discord.Forbidden, RuntimeError) as e:
            await interaction.followup.send(embed=style.error(f"보내지 못했습니다: 봇에 '웹후크 관리' 권한이 필요합니다. ({e})"),
                                            ephemeral=True)
            return
        await interaction.followup.send("보냈습니다.", ephemeral=True)
        await session_log(interaction, "rp", char["name"], text)

    # ---------- NPC ----------
    async def _npc_ac(self, interaction: discord.Interaction, current: str):
        npcs = await self.bot.db.list_npcs(interaction.guild_id)
        return [app_commands.Choice(name=n["name"], value=n["name"]) for n in npcs if current in n["name"]][:25]

    @npc.command(name="등록", description="NPC를 등록하거나 고칩니다. (GM)")
    @app_commands.describe(이름="NPC 이름", 이미지="얼굴 이미지 URL", 설명="GM용 메모")
    async def npc_add(self, interaction: discord.Interaction, 이름: app_commands.Range[str, 1, 80],
                      이미지: str | None = None, 설명: str = ""):
        if not await self._gm_only(interaction):
            return
        if 이미지 and not 이미지.startswith(("http://", "https://")):
            await interaction.response.send_message(embed=style.error("이미지는 http(s) 주소여야 합니다."), ephemeral=True)
            return
        await self.bot.db.upsert_npc(interaction.guild_id, 이름, 이미지, 설명)
        e = style.embed(title=이름, description=설명 or None)
        if 이미지:
            e.set_thumbnail(url=이미지)
        await interaction.response.send_message(content="NPC를 저장했습니다.", embed=e, ephemeral=True)

    @npc.command(name="대사", description="NPC로 말합니다. (GM)")
    @app_commands.autocomplete(이름=_npc_ac)
    @app_commands.describe(대사="NPC의 대사 (비우면 여러 줄 입력창)", 행동="행동 묘사", 타자효과="글자가 차례로 드러나게")
    async def npc_say(self, interaction: discord.Interaction, 이름: str, 대사: str | None = None,
                      행동: str | None = None, 타자효과: bool = False):
        if not await self._gm_only(interaction):
            return
        npc = await self.bot.db.get_npc(interaction.guild_id, 이름)
        if not npc:
            await interaction.response.send_message(embed=style.error("등록되지 않은 NPC입니다."), ephemeral=True)
            return

        async def run(inter: discord.Interaction, line: str | None):
            text = "\n".join(p for p in (f"*{행동}*" if 행동 else None, line) if p)
            if not text:
                await inter.response.send_message(embed=style.error("대사나 행동을 입력하세요."), ephemeral=True)
                return
            await inter.response.defer(ephemeral=True, thinking=False)
            try:
                if 타자효과:
                    await self._typed_webhook(inter.channel, npc, text)
                else:
                    await send_as(inter.channel, npc["name"], npc["avatar_url"], content=text)
            except (discord.Forbidden, RuntimeError) as e:
                await inter.followup.send(embed=style.error(f"보내지 못했습니다: 봇에 '웹후크 관리' 권한이 필요합니다. ({e})"),
                                          ephemeral=True)
                return
            await inter.followup.send("보냈습니다.", ephemeral=True)
            await session_log(inter, "npc", npc["name"], text)

        if 대사 is None and 행동 is None:
            await interaction.response.send_modal(TextModal(f"{이름}의 대사", run))
        else:
            await run(interaction, 대사.replace("\\n", "\n") if 대사 else None)

    async def _typed_webhook(self, channel, npc: dict, text: str) -> None:

        hook, thread = await webhook_for(channel)
        kwargs = dict(username=npc["name"][:80], avatar_url=npc["avatar_url"] or discord.utils.MISSING,
                      allowed_mentions=discord.AllowedMentions.none(), wait=True)
        if thread:
            kwargs["thread"] = thread
        parts = reveal_steps(text)
        msg = await hook.send(content=parts[0] + (CURSOR if len(parts) > 1 else ""), **kwargs)
        for i, part in enumerate(parts[1:], start=1):
            await asyncio.sleep(TYPE_INTERVAL)
            await hook.edit_message(msg.id, content=part + (CURSOR if i < len(parts) - 1 else ""),
                                    thread=thread or discord.utils.MISSING)

    @npc.command(name="목록", description="등록된 NPC를 봅니다.")
    async def npc_list(self, interaction: discord.Interaction):
        npcs = await self.bot.db.list_npcs(interaction.guild_id)
        if not npcs:
            await interaction.response.send_message(embed=style.embed(description="등록된 NPC가 없습니다."), ephemeral=True)
            return
        lines = [f"**{n['name']}**" + (f" · {n['description'][:80]}" if n["description"] else "") for n in npcs[:50]]
        await interaction.response.send_message(embed=style.embed(title="NPC", description="\n".join(lines)),
                                                ephemeral=True)

    @npc.command(name="삭제", description="NPC를 지웁니다. (GM)")
    @app_commands.autocomplete(이름=_npc_ac)
    async def npc_delete(self, interaction: discord.Interaction, 이름: str):
        if not await self._gm_only(interaction):
            return
        n = await self.bot.db.delete_npc(interaction.guild_id, 이름)
        await interaction.response.send_message(
            embed=style.embed(description=f"'{이름}'을(를) 지웠습니다." if n else "그 NPC가 없습니다."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(StoryCog(bot))
