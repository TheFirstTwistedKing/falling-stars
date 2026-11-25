import asyncio
import json

import pytest

from bot import lore


def run(coro):
    return asyncio.run(coro)


def test_database_roundtrip(tmp_path):
    from bot.db import Database

    async def go():
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        cid = await db.create_character(1, 2, "A", {"민첩": 60}, {"이성": {"cur": 50, "max": 99}})
        active = await db.get_active(1, 2)
        assert active["id"] == cid and active["stats"]["민첩"] == 60
        await db.update_character(cid, skills={"관찰": 55})
        assert (await db.get_character(cid))["skills"] == {"관찰": 55}
        sid = await db.start_session(1, 10, "s", 2)
        assert (await db.active_session(10))["id"] == sid
        await db.update_session(sid, initiative={"order": [{"name": "A", "value": 60}]})
        assert (await db.active_session(10))["initiative"]["order"][0]["name"] == "A"
        await db.log(sid, "chat", "A", "hi")
        await db.end_session(sid)
        assert await db.active_session(10) is None
        assert len(await db.get_logs(sid)) == 1
        await db.upsert_lore(1, "c", "n", "b", ["x"], 2)
        await db.upsert_lore(1, "c2", "n", "b2", [], 2)
        rows = await db.list_lore(1)
        assert len(rows) == 1 and rows[0]["category"] == "c2" and rows[0]["tags"] == []
        assert await db.delete_lore(1, "n") == 1
        await db.upsert_npc(1, "N", None, "")
        assert (await db.get_npc(1, "N"))["name"] == "N"
        assert await db.delete_npc(1, "N") == 1
        await db.delete_character(cid)
        assert await db.get_active(1, 2) is None
        await db.close()
    run(go())


def test_lore_file_and_search(tmp_path):
    p = tmp_path / "lore.json"
    p.write_text(json.dumps({"categories": {"K": [{"name": "Alpha", "body": "zzz", "tags": ["t1"]},
                                                  {"name": "Beta", "body": "alpha inside"}]}}))
    entries = lore.load_static(str(p))
    assert [e.name for e in lore.search(entries, "alpha")] == ["Alpha", "Beta"]
    assert lore.search(entries, "t1")[0].name == "Alpha"
    assert lore.search(entries, " ") == []


def test_shipped_lore_file_is_empty_template():
    from bot import config
    data = json.loads(open(config.LORE_PATH, encoding="utf-8").read())
    assert data == {"categories": {}}


def test_command_tree_builds(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.config.DB_PATH", str(tmp_path / "x.db"))
    from bot.main import EXTENSIONS, TRPGBot

    async def go():
        bot = TRPGBot()
        bot.db.path = str(tmp_path / "x.db")
        await bot.db.connect()
        for ext in EXTENSIONS:
            await bot.load_extension(ext)
        payload = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
        names = sorted(c["name"] for c in payload)
        await bot.db.close()
        return names, payload
    names, payload = run(go())
    assert names == sorted(["roll", "판정", "이성판정", "캐릭터", "세션", "전투", "도감", "서술", "장면", "말하기", "npc"])
    assert len(names) <= 100
    for cmd in payload:
        assert len(cmd["description"]) <= 100
        for opt in cmd.get("options", []):
            assert len(opt["description"]) <= 100
            for sub in opt.get("options", []) or []:
                assert len(sub["description"]) <= 100
