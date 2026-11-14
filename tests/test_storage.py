# coding: utf-8
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

import scraper
from tests.common import UTC_NOW, fixture


def default_mapping():
    mapping = {
        scraper.board_url("daily", "all"): fixture("daily_all.html"),
        scraper.board_url("weekly", "all"): fixture("weekly_all.html"),
    }
    for lang in scraper.DEFAULT_LANGUAGES:
        mapping[scraper.board_url("daily", lang)] = fixture("python_daily.html")
    return mapping


def run_with_mapping(data_dir, mapping, now=UTC_NOW):
    def fake_fetch(url, **kwargs):
        if url not in mapping:
            raise scraper.ScrapeError("未预期的榜单地址: " + url)
        html = mapping[url]
        if isinstance(html, Exception):
            raise html
        return html

    with mock.patch.object(scraper, "fetch_board", side_effect=fake_fetch), \
            mock.patch.dict(os.environ, {}, clear=True):
        return scraper.run_scrape(data_dir, now_utc=now)


class SaveRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = self.tmp.name

    def read_json(self, rel):
        with open(os.path.join(self.data_dir, rel), encoding="utf-8") as handle:
            return json.load(handle)

    def test_multi_board_single_metadata(self):
        snapshot = run_with_mapping(self.data_dir, default_mapping())
        self.assertEqual(snapshot["date"], "2026-11-15")
        self.assertEqual(snapshot["timezone"], "Asia/Shanghai")
        self.assertEqual(snapshot["fetched_at"], "2026-11-15T02:00:12Z")
        self.assertEqual(len(snapshot["boards"]), 8)

        repos = self.read_json("repos.json")["repositories"]
        self.assertEqual(
            sorted(repos),
            ["another-org/tools", "example/project", "py-only/lib",
             "third/repo", "weekly-only/repo"],
        )
        self.assertEqual(repos["example/project"]["full_name"], "Example/Project")
        self.assertEqual(repos["example/project"]["first_seen"], "2026-11-15")
        self.assertEqual(repos["example/project"]["last_seen"], "2026-11-15")

        daily = snapshot["boards"][0]["entries"][0]
        weekly = snapshot["boards"][1]["entries"][0]
        self.assertEqual(daily["repo_key"], "example/project")
        self.assertEqual(weekly["repo_key"], "example/project")
        self.assertEqual(daily["stars"], 12345)
        self.assertEqual(weekly["stars"], 12400)
        self.assertEqual(daily["stars_in_period"], 321)
        self.assertEqual(weekly["stars_in_period"], 1500)

        self.assertTrue(
            os.path.exists(
                os.path.join(self.data_dir, "snapshots", "2026", "11", "2026-11-15.json")
            )
        )

    def test_date_boundary_shanghai(self):
        cases = [
            (datetime.datetime(2026, 11, 14, 15, 59, 59, tzinfo=datetime.timezone.utc),
             "2026-11-14"),
            (datetime.datetime(2026, 11, 14, 16, 0, 0, tzinfo=datetime.timezone.utc),
             "2026-11-15"),
        ]
        for now, expected in cases:
            snapshot = run_with_mapping(self.data_dir, default_mapping(), now=now)
            self.assertEqual(snapshot["date"], expected)

    def test_rerun_same_day_overwrites(self):
        run_with_mapping(self.data_dir, default_mapping())
        changed = dict(default_mapping())
        changed[scraper.board_url("daily", "all")] = fixture("weekly_all.html")
        run_with_mapping(self.data_dir, changed)

        snapshot_dir = os.path.join(self.data_dir, "snapshots", "2026", "11")
        self.assertEqual(os.listdir(snapshot_dir), ["2026-11-15.json"])
        snapshot = self.read_json("snapshots/2026/11/2026-11-15.json")
        self.assertEqual(snapshot["boards"][0]["entries"][0]["stars"], 12400)
        repos = self.read_json("repos.json")["repositories"]
        self.assertEqual(repos["example/project"]["first_seen"], "2026-11-15")

    def test_next_day_keeps_first_seen_and_unlisted_repos(self):
        run_with_mapping(self.data_dir, default_mapping())
        next_day = UTC_NOW + datetime.timedelta(days=1)
        smaller = {
            scraper.board_url("daily", "all"): fixture("daily_all.html"),
            scraper.board_url("weekly", "all"): fixture("daily_all.html"),
        }
        for lang in scraper.DEFAULT_LANGUAGES:
            smaller[scraper.board_url("daily", lang)] = fixture("daily_all.html")
        run_with_mapping(self.data_dir, smaller, now=next_day)

        repos = self.read_json("repos.json")["repositories"]
        self.assertEqual(repos["example/project"]["first_seen"], "2026-11-15")
        self.assertEqual(repos["example/project"]["last_seen"], "2026-11-16")
        self.assertIn("weekly-only/repo", repos)
        self.assertEqual(repos["weekly-only/repo"]["last_seen"], "2026-11-15")

    def test_fetch_failure_keeps_existing_json(self):
        run_with_mapping(self.data_dir, default_mapping())
        files = ["repos.json", "snapshots/2026/11/2026-11-15.json"]
        before = {}
        for rel in files:
            with open(os.path.join(self.data_dir, rel), "rb") as handle:
                before[rel] = handle.read()
        broken = dict(default_mapping())
        broken[scraper.board_url("weekly", "all")] = scraper.ScrapeError("模拟抓取失败")
        with self.assertRaises(scraper.ScrapeError):
            run_with_mapping(self.data_dir, broken)
        for rel in files:
            with open(os.path.join(self.data_dir, rel), "rb") as handle:
                self.assertEqual(handle.read(), before[rel])

    def test_parse_failure_keeps_existing_json(self):
        run_with_mapping(self.data_dir, default_mapping())
        path = os.path.join(self.data_dir, "repos.json")
        with open(path, "rb") as handle:
            before = handle.read()
        broken = dict(default_mapping())
        broken[scraper.board_url("daily", "go")] = fixture("empty.html")
        with self.assertRaises(scraper.ScrapeError):
            run_with_mapping(self.data_dir, broken)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_no_temp_files_left(self):
        run_with_mapping(self.data_dir, default_mapping())
        for root, _, names in os.walk(self.data_dir):
            for name in names:
                self.assertFalse(name.startswith(".tmp-"), os.path.join(root, name))


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.board, self.metas = scraper.parse_board(
            fixture("daily_all.html"), "daily", "all", "https://github.com/trending?since=daily"
        )
        self.repos_doc = scraper.merge_repositories(
            {"schema_version": 1, "repositories": {}}, [self.metas], "2026-11-15"
        )
        self.snapshot = {
            "schema_version": 1,
            "date": "2026-11-15",
            "timezone": "Asia/Shanghai",
            "fetched_at": "2026-11-15T02:00:12Z",
            "boards": [self.board],
        }

    def test_valid_snapshot_passes(self):
        scraper.validate_snapshot(self.snapshot, self.repos_doc["repositories"])

    def test_missing_repo_reference_fails(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.validate_snapshot(self.snapshot, {})

    def test_duplicate_board_fails(self):
        self.snapshot["boards"] = [self.board, self.board]
        with self.assertRaises(scraper.ScrapeError):
            scraper.validate_snapshot(self.snapshot, self.repos_doc["repositories"])

    def test_non_continuous_rank_fails(self):
        self.board["entries"][1]["rank"] = 5
        with self.assertRaises(scraper.ScrapeError):
            scraper.validate_snapshot(self.snapshot, self.repos_doc["repositories"])

    def test_negative_metric_fails(self):
        self.board["entries"][0]["stars"] = -1
        with self.assertRaises(scraper.ScrapeError):
            scraper.validate_snapshot(self.snapshot, self.repos_doc["repositories"])


if __name__ == "__main__":
    unittest.main()