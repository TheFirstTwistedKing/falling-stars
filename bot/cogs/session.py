"""/세션 ..., /전투 ... GM 세션 관리와 전투 순서"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .. import config, style
from ..helpers import is_gm, session_log

KST = timezone(timedelta(hours=9))


def _fmt_time(ts: float, fmt: str = "%H:%M") -> str:
    return datetime.fromtimestamp(ts, KST).strftime(fmt)


def initiative_embed(state: dict) -> discord.Embed:
    order = state.get("order", [])
    idx = state.get("index", 0)
    lines = []
    for i, entry in enumerate(order):
        marker = "▶" if state.get("started") and i == idx else "　"
        lines.append(f"{marker} `{entry['value']:>3}` {entry['name']}")
    title = f"전투 · {state.get('round', 1)}라운드" if state.get("started") else "전투 준비"
    e = style.embed(title=title, description="\n".join(lines) or "참가자가 없습니다.",
                    colour=style.DEEP if state.get("started") else style.SKY)
    if state.get("started") and order:
        e.set_footer(text=f"지금 차례: {order[idx]['name']}")
    return e


class SessionCog(commands.Cog):
    session = app_commands.Group(name="세션", description="TRPG 세션 관리", guild_only=True)
    combat = app_commands.Group(name="전투", description="전투 순서(민첩 순)", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.active: dict[int, int] = {}  # channel_id -> session_id

    async def cog_load(self):
        for s in await self.bot.db.all_active_sessions():
            self.active[s["channel_id"]] = s["id"]

    async def _gm_only(self, interaction: discord.Interaction) -> bool:
        if await is_gm(interaction):
            return True
        await interaction.response.send_message(
            embed=style.error(f"GM만 쓸 수 있습니다. (세션 GM, '{config.GM_ROLE_NAME}' 역할, 서버 관리 권한)"),
            ephemeral=True)
        return False

    async def _session_or_error(self, interaction: discord.Interaction) -> dict | None:
        s = await self.bot.db.active_session(interaction.channel_id)
        if not s:
            await interaction.response.send_message(
                embed=style.error("이 채널에 진행 중인 세션이 없습니다. `/세션 시작`을 먼저 하세요."), ephemeral=True)
        return s

    # ---------- 세션 ----------
    @session.command(name="시작", description="이 채널에서 세션을 시작합니다. 시작한 사람이 GM이 됩니다.")
    @app_commands.describe(이름="세션 이름")
    async def start(self, interaction: discord.Interaction, 이름: app_commands.Range[str, 1, 80]):
        if await self.bot.db.active_session(interaction.channel_id):
            await interaction.response.send_message(
                embed=style.error("이 채널에는 이미 진행 중인 세션이 있습니다."), ephemeral=True)
            return
        sid = await self.bot.db.start_session(interaction.guild_id, interaction.channel_id, 이름,
                                              interaction.user.id)
        self.active[interaction.channel_id] = sid
        await self.bot.db.log(sid, "system", "GM", f"세션 시작: {이름}")
        e = style.embed(title=이름, description="세션이 시작되었습니다.", colour=style.LEMON)
        e.add_field(name="GM", value=interaction.user.mention)
        e.add_field(name="채팅 기록", value="켜짐" if config.LOG_CHAT else "명령어 결과만", inline=True)
        await interaction.response.send_message(embed=e)

    @session.command(name="상태", description="진행 중인 세션 정보를 봅니다.")
    async def status(self, interaction: discord.Interaction):
        s = await self._session_or_error(interaction)
        if not s:
            return
        logs = await self.bot.db.get_logs(s["id"])
        e = style.embed(title=s["name"])
        e.add_field(name="GM", value=f"<@{s['gm_id']}>")
        e.add_field(name="시작", value=_fmt_time(s["started_at"], "%m/%d %H:%M"))
        e.add_field(name="기록", value=f"{len(logs)}줄")
        if s["scene"]:
            e.add_field(name="현재 장면", value=s["scene"][:1024], inline=False)
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    @session.command(name="종료", description="세션을 끝내고 기록을 파일로 내보냅니다.")
    async def end(self, interaction: discord.Interaction):
        s = await self._session_or_error(interaction)
        if not s or not await self._gm_only(interaction):
            return
        await self.bot.db.log(s["id"], "system", "GM", "세션 종료")
        await self.bot.db.end_session(s["id"])
        self.active.pop(interaction.channel_id, None)
        logs = await self.bot.db.get_logs(s["id"])
        lines = [f"# {s['name']}", f"# {_fmt_time(s['started_at'], '%Y-%m-%d %H:%M')} KST", ""]
        for row in logs:
            lines.append(f"[{_fmt_time(row['ts'])}] ({row['kind']}) {row['author']}: {row['content']}")
        buf = io.BytesIO("\n".join(lines).encode("utf-8"))
        file = discord.File(buf, filename=f"session-{s['id']}.txt")
        e = style.embed(title=s["name"], description=f"세션이 끝났습니다. 기록 {len(logs)}줄.")
        await interaction.response.send_message(embed=e, file=file)

    # ---------- 전투 ----------
    async def _state(self, s: dict) -> dict:
        state = s["initiative"] or {}
        state.setdefault("order", [])
        state.setdefault("index", 0)
        state.setdefault("round", 1)
        state.setdefault("started", False)
        return state

    @combat.command(name="추가", description="전투 참가자를 추가합니다. 비우면 내 캐릭터를 민첩으로 추가합니다.")
    @app_commands.describe(이름="NPC 등 참가자 이름", 민첩="순서 값")
    async def combat_add(self, interaction: discord.Interaction, 이름: str | None = None,
                         민첩: app_commands.Range[int, 0, 200] | None = None):
        s = await self._session_or_error(interaction)
        if not s:
            return
        if 이름 is None or 민첩 is None:
            char = await self.bot.db.get_active(interaction.guild_id, interaction.user.id)
            if not char:
                await interaction.response.send_message(
                    embed=style.error("이름과 민첩을 입력하거나 캐릭터를 먼저 선택하세요."), ephemeral=True)
                return
            이름 = 이름 or char["name"]
            민첩 = 민첩 if 민첩 is not None else int(char["stats"].get("민첩", 0))
        state = await self._state(s)
        state["order"] = [o for o in state["order"] if o["name"] != 이름]
        state["order"].append({"name": 이름, "value": 민첩})
        state["order"].sort(key=lambda o: -o["value"])
        await self.bot.db.update_session(s["id"], initiative=state)
        await interaction.response.send_message(embed=initiative_embed(state))

    @combat.command(name="제외", description="참가자를 전투 순서에서 뺍니다.")
    async def combat_remove(self, interaction: discord.Interaction, 이름: str):
        s = await self._session_or_error(interaction)
        if not s:
            return
        state = await self._state(s)
        names = [o["name"] for o in state["order"]]
        if 이름 not in names:
            await interaction.response.send_message(embed=style.error("그 참가자가 없습니다."), ephemeral=True)
            return
        removed_idx = names.index(이름)
        state["order"].pop(removed_idx)
        if removed_idx < state["index"]:
            state["index"] -= 1
        if state["order"]:
            state["index"] %= len(state["order"])
        else:
            state["index"] = 0
        await self.bot.db.update_session(s["id"], initiative=state)
        await interaction.response.send_message(embed=initiative_embed(state))

    @combat.command(name="시작", description="전투를 시작합니다. (GM)")
    async def combat_start(self, interaction: discord.Interaction):
        s = await self._session_or_error(interaction)
        if not s or not await self._gm_only(interaction):
            return
        state = await self._state(s)
        if not state["order"]:
            await interaction.response.send_message(embed=style.error("참가자를 먼저 추가하세요."), ephemeral=True)
            return
        state.update(started=True, index=0, round=1)
        await self.bot.db.update_session(s["id"], initiative=state)
        await session_log(interaction, "combat", "GM", "전투 시작: " + ", ".join(o["name"] for o in state["order"]))
        await interaction.response.send_message(embed=initiative_embed(state))

    @combat.command(name="다음", description="다음 차례로 넘깁니다.")
    async def combat_next(self, interaction: discord.Interaction):
        s = await self._session_or_error(interaction)
        if not s:
            return
        state = await self._state(s)
        if not state["started"] or not state["order"]:
            await interaction.response.send_message(embed=style.error("진행 중인 전투가 없습니다."), ephemeral=True)
            return
        state["index"] += 1
        if state["index"] >= len(state["order"]):
            state["index"] = 0
            state["round"] += 1
        await self.bot.db.update_session(s["id"], initiative=state)
        await interaction.response.send_message(embed=initiative_embed(state))

    @combat.command(name="종료", description="전투를 끝냅니다. (GM)")
    async def combat_end(self, interaction: discord.Interaction):
        s = await self._session_or_error(interaction)
        if not s or not await self._gm_only(interaction):
            return
        state = await self._state(s)
        rounds = state["round"]
        await self.bot.db.update_session(s["id"], initiative={})
        await session_log(interaction, "combat", "GM", f"전투 종료 ({rounds}라운드)")
        await interaction.response.send_message(
            embed=style.embed(description=f"전투가 끝났습니다. {rounds}라운드."))

    # ---------- 채팅 기록 ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not config.LOG_CHAT or message.author.bot or message.webhook_id or not message.guild:
            return
        sid = self.active.get(message.channel.id)
        if sid and message.content:
            await self.bot.db.log(sid, "chat", message.author.display_name, message.content[:2000])


async def setup(bot):
    await bot.add_cog(SessionCog(bot))
