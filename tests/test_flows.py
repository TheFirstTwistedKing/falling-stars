"""가짜 Interaction으로 실제 명령 콜백을 실행하는 흐름 테스트."""
import asyncio
from types import SimpleNamespace

import discord

from bot.main import EXTENSIONS, TRPGBot


class FakeResponse:
    def __init__(self, inter):
        self.inter, self.done = inter, False

    def is_done(self):
        return self.done

    async def send_message(self, content=None, *, embed=None, file=None, ephemeral=False, **kw):
        self.done = True
        self.inter.sent.append(SimpleNamespace(content=content, embed=embed, file=file, ephemeral=ephemeral))

    async def defer(self, **kw):
        self.done = True

    async def send_modal(self, modal):
        self.done = True
        self.inter.sent.append(SimpleNamespace(modal=modal, embed=None, content=None, file=None, ephemeral=True))


class FakeFollowup:
    def __init__(self, inter):
        self.inter = inter

    async def send(self, content=None, *, embed=None, ephemeral=False, **kw):
        self.inter.sent.append(SimpleNamespace(content=content, embed=embed, file=None, ephemeral=ephemeral))


def make_inter(bot, user_id=2, channel_id=10):
    user = SimpleNamespace(id=user_id, display_name=f"user{user_id}", mention=f"<@{user_id}>",
                           display_avatar=SimpleNamespace(url="https://example.invalid/a.png"))
    inter = SimpleNamespace(guild_id=1, channel_id=channel_id, channel=None, user=user, client=bot, sent=[])
    inter.response = FakeResponse(inter)
    inter.followup = FakeFollowup(inter)

    async def edit_original_response(embed=None, **kw):
        inter.sent.append(SimpleNamespace(content=None, embed=embed, file=None, ephemeral=False, edit=True))
    inter.edit_original_response = edit_original_response
    return inter


def test_full_flow(tmp_path, monkeypatch):
    async def go():
        bot = TRPGBot()
        bot.db.path = str(tmp_path / "f.db")
        await bot.db.connect()
        for ext in EXTENSIONS:
            await bot.load_extension(ext)
        monkeypatch.setattr(bot.extensions["bot.cogs.story"], "TYPE_INTERVAL", 0)
        admins = {99}
        monkeypatch.setattr(bot.extensions["bot.cogs.character"], "is_admin",
                            lambda inter: inter.user.id in admins)
        ch, dice, sess, lore_cog, st = (bot.get_cog(n) for n in
                                        ("CharacterCog", "DiceCog", "SessionCog", "LoreCog", "StoryCog"))

        player = make_inter(bot).user

        # 플레이어는 캐릭터를 만들거나 고칠 수 없다
        i = make_inter(bot); await ch.create.callback(ch, i, player, "몰래", "랜덤")
        assert i.sent[0].ephemeral and "관리자" in i.sent[0].embed.description
        assert await bot.db.list_characters(1) == []

        # 관리자가 플레이어(2)에게 캐릭터를 만들어 준다 → 플레이어의 선택 캐릭터가 된다
        i = make_inter(bot, user_id=99); await ch.create.callback(ch, i, player, "탐사자", "랜덤")
        assert "탐사자" == i.sent[0].embed.title
        assert (await bot.db.get_active(1, 2))["name"] == "탐사자"
        assert await bot.db.get_active(1, 99) is None

        i = make_inter(bot, user_id=99); await ch.set_skill.callback(ch, i, player, "탐사자", "관찰", 70)
        before = await bot.db.get_active(1, 2)
        for call in (lambda i: ch.set_stat.callback(ch, i, player, "탐사자", "근력", 99),
                     lambda i: ch.set_skill.callback(ch, i, player, "탐사자", "관찰", 99),
                     lambda i: ch.decorate.callback(ch, i, player, "탐사자", None, "x"),
                     lambda i: ch.delete.callback(ch, i, player, "탐사자", "탐사자")):
            i = make_inter(bot); await call(i)
            assert i.sent[0].ephemeral and "관리자" in i.sent[0].embed.description
        assert await bot.db.get_active(1, 2) == before

        # 관리자 대상 지정이 틀리면 거부
        i = make_inter(bot, user_id=99); await ch.set_stat.callback(ch, i, player, "없는이름", "근력", 50)
        assert "없습니다" in i.sent[0].embed.description

        # 플레이어는 배정된 캐릭터를 선택할 수 있다
        i = make_inter(bot); await ch.select.callback(ch, i, "탐사자")
        assert "선택했습니다" in i.sent[0].embed.description
        i = make_inter(bot); await dice.check.callback(dice, i, "관찰", None, 0, 0, "보통", False)
        assert i.sent[0].embed.author.name.startswith("탐사자 · 관찰 70")

        # 세션 없이 GM 명령은 거부
        i = make_inter(bot, user_id=3); await st.narrate.callback(st, i, "x", None, False)
        assert i.sent[0].ephemeral and "GM" in i.sent[0].embed.description

        i = make_inter(bot); await sess.start.callback(sess, i, "첫 세션")
        i = make_inter(bot); await dice.roll.callback(dice, i, "2d6+1", "테스트", False)
        i = make_inter(bot); await dice.sanity.callback(dice, i, "0", "1d6")
        char = await bot.db.get_active(1, 2)
        assert char["resources"]["이성"]["cur"] <= char["stats"]["정신"]

        long = "빛이 떨어진다. " * 30
        i = make_inter(bot); await st.narrate.callback(st, i, long, "서막", True)
        assert i.sent[-1].embed.description == long and len(i.sent) >= 2
        assert all(not s.embed.description.endswith("▌") for s in i.sent[-1:])

        i = make_inter(bot); await st.scene.callback(st, i, "장면1", "설명", None)
        i = make_inter(bot); await sess.combat_add.callback(sess, i, None, None)
        i = make_inter(bot); await sess.combat_add.callback(sess, i, "적", 99)
        i = make_inter(bot); await sess.combat_start.callback(sess, i)
        assert i.sent[0].embed.footer.text == "지금 차례: 적"
        i = make_inter(bot); await sess.combat_next.callback(sess, i)
        i = make_inter(bot); await sess.combat_next.callback(sess, i)
        assert "2라운드" in i.sent[0].embed.title
        i = make_inter(bot); await sess.combat_remove.callback(sess, i, "적")
        i = make_inter(bot); await sess.combat_end.callback(sess, i)

        i = make_inter(bot); await ch.resource.callback(ch, i, "체력", "-100", None)
        assert i.sent[0].embed.title.endswith("→ 0")
        i = make_inter(bot); await ch.resource.callback(ch, i, "체력", "abc", None)
        assert i.sent[0].ephemeral

        i = make_inter(bot); await lore_cog.list_.callback(lore_cog, i, None)
        assert "비어" in i.sent[0].embed.description
        await bot.db.upsert_lore(1, "분류", "항목", "본문", ["검색어"], 2)
        i = make_inter(bot); await lore_cog.find.callback(lore_cog, i, "검색어")
        assert i.sent[0].embed.title == "항목"

        i = make_inter(bot); await ch.view.callback(ch, i, None, None)
        assert i.sent[0].embed.fields
        i = make_inter(bot, user_id=99); await ch.delete.callback(ch, i, player, "탐사자", "탐사자")
        assert await bot.db.list_characters(1) == []
        i = make_inter(bot); await sess.end.callback(sess, i)
        data = i.sent[0].file.fp.read().decode()
        for word in ("세션 시작", "2d6+1", "이성판정", "[서막]", "장면1", "전투 시작", "체력", "세션 종료"):
            assert word in data, word
        await bot.db.close()
    asyncio.run(go())
