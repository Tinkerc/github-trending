import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import archive_history


class HistoryArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"

    def source(self, date, content):
        path = self.root / date[:4] / f"{date}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_early_format_multiline_and_source(self):
        path = self.source("2015-08-18", """###2015-08-18

####python
* <img src='avatar' height='20'>[Owner / Repo](https://github.com/Owner/Repo): 中文
第二行 [说明](https://example.com)
**privately**
#15 Trending Project (All Languages)

####swift
* [Other / Lib](https://github.com/Other/Lib):
""")
        snapshot, metas = archive_history.parse_markdown(path, self.root)
        entry = snapshot["boards"][0]["entries"][0]
        self.assertEqual(entry["description"], "中文\n第二行 [说明](https://example.com)\n**privately**\n#15 Trending Project (All Languages)")
        self.assertEqual(entry["source_line"], 4)
        self.assertEqual(entry["repo_key"], "owner/repo")
        self.assertEqual(entry["name"], "Owner / Repo")
        self.assertEqual(metas[0]["description"], entry["description"])
        self.assertIsNone(metas[0]["language"])
        self.assertIsNone(entry["stars"])
        self.assertIsNone(snapshot["fetched_at"])
        self.assertEqual(snapshot["source_file"], "2015/2015-08-18.md")
        self.assertEqual(snapshot["source_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(snapshot["boards"][1]["entries"][0]["description"], "")

    def test_references_duplicates_empty_board_and_repeatability(self):
        self.source("2024-01-01", """## 2024-01-01
#### HTML
* [Owner / Repo](https://github.com/Owner/Repo): 旧简介
* [Owner / Repo](https://github.com/Owner/Repo): 重复观察
#### TypeScript
""")
        self.source("2024-01-02", """## 2024-01-02
#### python
* [OWNER / REPO](https://github.com/OWNER/REPO): 新简介
""")
        self.data.mkdir()
        live = self.data / "repos.json"
        live.write_text('{"untouched": true}\n')
        before_live = live.read_bytes()
        result = archive_history.archive_history(self.root, self.data)
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["entries"], 3)
        self.assertEqual(result["boards"], 3)
        self.assertEqual(result["repositories"], 1)
        archived = self.data / "history"
        repos = json.loads((archived / "repos.json").read_text())["repositories"]
        self.assertEqual(repos["owner/repo"]["first_seen"], "2024-01-01")
        self.assertEqual(repos["owner/repo"]["last_seen"], "2024-01-02")
        self.assertEqual(repos["owner/repo"]["description"], "新简介")
        snapshot = json.loads((archived / "snapshots/2024/01/2024-01-01.json").read_text())
        self.assertEqual([e["rank"] for e in snapshot["boards"][0]["entries"]], [1, 2])
        self.assertEqual(snapshot["boards"][0]["language_filter"], "html")
        self.assertEqual(snapshot["boards"][1]["entries"], [])
        before = {p: p.read_bytes() for p in archived.rglob("*.json")}
        archive_history.archive_history(self.root, self.data)
        self.assertEqual(before, {p: p.read_bytes() for p in archived.rglob("*.json")})
        self.assertEqual(live.read_bytes(), before_live)
        self.assertTrue((self.root / "2024/2024-01-01.md").exists())

    def test_invalid_inputs_fail_before_writing(self):
        self.source("2024-01-01", "## 2024-01-01\n#### python\n")
        for content in (
            "## 2024-01-03\n#### python\n",
            "## 2024-01-02\n* [a](https://github.com/a/b): x\n",
            "## 2024-01-02\n#### python\n* broken link\n",
            "## 2024-01-02\n#### python\n* [a](https://example.com/a/b): x\n",
            "## 2024-01-02\n#### python\n* [a](https://github.com/a/b/issues): x\n",
            "## 2024-01-02\n#### python\n#### python\n",
            "#### python\n",
        ):
            with self.subTest(content=content):
                self.source("2024-01-02", content)
                with self.assertRaises(ValueError):
                    archive_history.archive_history(self.root, self.data)
                self.assertFalse(self.data.exists())

    def test_no_sources(self):
        with self.assertRaisesRegex(ValueError, "没有找到"):
            archive_history.archive_history(self.root, self.data)

    def test_date_only_source_is_archived_as_empty(self):
        self.source("2018-03-26", "## 2018-03-26\n")
        result = archive_history.archive_history(self.root, self.data)
        self.assertEqual(result["empty_files"], 1)
        self.assertEqual(result["entries"], 0)
        path = self.data / "history/snapshots/2018/03/2018-03-26.json"
        self.assertEqual(json.loads(path.read_text())["boards"], [])


if __name__ == "__main__":
    unittest.main()
