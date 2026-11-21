#!/usr/bin/env python3
"""Проверки данных каталога в index.html (без сети).

Запуск: python3 -m unittest discover -s tests   (или ./test.sh)
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
COVERS = ROOT / "covers"

# Те же регулярки, что в auto_add.py: если они перестанут находить данные,
# автодобавление тоже сломается.
BGG_RE = re.compile(r"const BGG=(\{.*?\});", re.DOTALL)
D_RE = re.compile(r"const D=(\[.*?\]);", re.DOTALL)
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

# Известные листинги без записи в BGG (BGG ID ещё не проверен через поиск —
# угадывать нельзя). Добавить запись в BGG и убрать отсюда.
KNOWN_NO_BGG = {"Cluedo: Sherlock Holmes Edition"}


def load():
    src = HTML.read_text(encoding="utf-8")
    bgg_m, d_m = BGG_RE.search(src), D_RE.search(src)
    assert bgg_m and d_m, "const BGG= / const D= не найдены в index.html"
    return json.loads(bgg_m.group(1)), json.loads(d_m.group(1))


class CatalogData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.BGG, cls.D = load()

    def test_parsed(self):
        self.assertIsInstance(self.BGG, dict)
        self.assertIsInstance(self.D, list)
        self.assertGreater(len(self.D), 0)

    def test_listing_fields(self):
        for i, r in enumerate(self.D):
            with self.subTest(i=i, t=r.get("t")):
                self.assertIsInstance(r.get("t"), str)
                self.assertTrue(r["t"].strip())
                p = r.get("p")
                self.assertTrue(p is None or (isinstance(p, (int, float)) and p >= 0))
                self.assertIn(r.get("l"), ("ENG", "РУС", "", None))
                m = r.get("m")
                self.assertTrue(m is None or isinstance(m, int))
                if "x" in r:
                    self.assertIsInstance(r["x"], bool)

    def test_dates(self):
        # pd() в index.html понимает дд.мм.гггг или просто год
        for r in self.D:
            d = r.get("d") or ""
            with self.subTest(t=r.get("t"), d=d):
                self.assertTrue(len(d) <= 4 or DATE_RE.match(d))

    def test_listing_has_bgg_entry(self):
        # Правило из CLAUDE.md: D[i].t точно совпадает с ключом BGG
        missing = {r["t"] for r in self.D if r["t"] not in self.BGG}
        self.assertEqual(sorted(missing - KNOWN_NO_BGG), [], "листинги без записи в BGG")

    def test_bgg_entries(self):
        for k, b in self.BGG.items():
            with self.subTest(k=k):
                self.assertIsInstance(b, dict)
                self.assertIsInstance(b.get("bgg_id"), int)
                u = b.get("bgg_url") or ""
                self.assertTrue(u == "" or u.startswith("https://boardgamegeek.com/"))

    def test_covers_exist(self):
        # Отчёт, а не падение: без обложки карточка берёт BGG image / эмодзи
        ids = {self.BGG[r["t"]]["bgg_id"] for r in self.D if r["t"] in self.BGG}
        ids.discard(0)
        missing = sorted(i for i in ids if not (COVERS / f"{i}.webp").exists())
        if missing:
            print(f"\n[инфо] нет covers/*.webp для bgg_id: {missing}")


if __name__ == "__main__":
    unittest.main()
