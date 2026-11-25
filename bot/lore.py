"""세계관 도감. data/lore.json(고정 설정)과 서버별 DB 항목을 합쳐 보여준다.

lore.json 형식:
{
  "categories": {
    "<분류 이름>": [
      {"name": "<항목 이름>", "body": "<설명>", "tags": ["<검색어>"]}
    ]
  }
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LoreEntry:
    category: str
    name: str
    body: str
    tags: list[str] = field(default_factory=list)
    source: str = "설정집"


def load_static(path: str) -> list[LoreEntry]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = []
    for category, items in (data.get("categories") or {}).items():
        for item in items or []:
            entries.append(LoreEntry(category=category, name=item["name"],
                                     body=item.get("body", ""), tags=item.get("tags", [])))
    return entries


def search(entries: list[LoreEntry], keyword: str) -> list[LoreEntry]:
    k = keyword.strip().lower()
    if not k:
        return []
    exact = [e for e in entries if e.name.lower() == k]
    partial = [e for e in entries if e not in exact and (
        k in e.name.lower() or any(k in t.lower() for t in e.tags) or k in e.body.lower())]
    return exact + partial
