"""권한 확인, 웹훅 전송 등 공통 도우미."""
from __future__ import annotations

import discord

from . import config

WEBHOOK_NAME = "TRPG Narrator"


def is_admin(interaction: discord.Interaction) -> bool:
    """관리자 판정: 서버 관리 권한 또는 GM 역할. (세션 GM이라는 것만으로는 아님)"""
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return member.guild_permissions.manage_guild or any(r.name == config.GM_ROLE_NAME for r in member.roles)


async def is_gm(interaction: discord.Interaction) -> bool:
    """GM 판정: 서버 관리 권한, GM 역할, 또는 이 채널 진행 중 세션의 GM."""
    member = interaction.user
    if isinstance(member, discord.Member):
        if member.guild_permissions.manage_guild:
            return True
        if any(r.name == config.GM_ROLE_NAME for r in member.roles):
            return True
    db = interaction.client.db
    session = await db.active_session(interaction.channel_id)
    return bool(session and session["gm_id"] == member.id)


async def webhook_for(channel: discord.abc.GuildChannel | discord.Thread) -> tuple[discord.Webhook, discord.Thread | None]:
    thread = None
    if isinstance(channel, discord.Thread):
        thread = channel
        channel = channel.parent
    if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
        raise RuntimeError("이 채널에서는 웹훅을 쓸 수 없습니다.")
    for hook in await channel.webhooks():
        if hook.name == WEBHOOK_NAME and hook.token:
            return hook, thread
    hook = await channel.create_webhook(name=WEBHOOK_NAME)
    return hook, thread


async def send_as(channel, name: str, avatar_url: str | None, content: str | None = None,
                  embed: discord.Embed | None = None) -> None:
    """NPC나 캐릭터 이름·얼굴로 메시지를 보낸다. 웹훅 관리 권한이 필요하다."""
    hook, thread = await webhook_for(channel)
    kwargs = dict(username=name[:80], avatar_url=avatar_url or discord.utils.MISSING,
                  allowed_mentions=discord.AllowedMentions.none())
    if content:
        kwargs["content"] = content
    if embed:
        kwargs["embed"] = embed
    if thread:
        kwargs["thread"] = thread
    await hook.send(**kwargs)


async def session_log(interaction: discord.Interaction, kind: str, author: str, content: str) -> None:
    """이 채널에 진행 중인 세션이 있으면 로그에 남긴다."""
    session = await interaction.client.db.active_session(interaction.channel_id)
    if session:
        await interaction.client.db.log(session["id"], kind, author, content)
