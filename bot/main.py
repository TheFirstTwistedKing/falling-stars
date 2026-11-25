"""봇 진입점: python -m bot.main"""
from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from . import config, style
from .db import Database

EXTENSIONS = (
    "bot.cogs.dice_cog",
    "bot.cogs.character",
    "bot.cogs.session",
    "bot.cogs.lore_cog",
    "bot.cogs.story",
)

log = logging.getLogger("trpg")


class TRPGBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = config.LOG_CHAT  # 채팅 기록을 켤 때만 필요(개발자 포털에서도 켜야 함)
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.db = Database(config.DB_PATH)

    async def setup_hook(self) -> None:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.tree.on_error = self.on_app_command_error
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("개발 서버에 명령 %d개 동기화", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("전역 명령 %d개 동기화 (반영까지 최대 1시간)", len(synced))

    async def on_ready(self) -> None:
        log.info("로그인: %s (%s)", self.user, self.user.id if self.user else "-")

    async def close(self) -> None:
        await self.db.close()
        await super().close()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        log.exception("명령 오류", exc_info=error)
        msg = "명령을 처리하다 문제가 생겼습니다."
        if isinstance(error, app_commands.NoPrivateMessage):
            msg = "서버 채널에서만 쓸 수 있습니다."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=style.error(msg), ephemeral=True)
            else:
                await interaction.response.send_message(embed=style.error(msg), ephemeral=True)
        except discord.HTTPException:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN이 없습니다. .env.example을 .env로 복사하고 토큰을 넣으세요.")
    TRPGBot().run(config.TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
