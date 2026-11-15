# coding: utf-8
import json
from pathlib import Path
import tempfile
import unittest

import trends


def snapshot(date, daily=(), weekly=(), language=()):
    def board(period, lang, values):
        return {"period": period, "language_filter": lang, "entries": [
            {"repo_key": key, "rank": rank, "stars_in_period": growth}
            for rank, (key, growth) in enumerate(values, 1)
        ]}
    return {"date": date, "boards": [
        board("daily", "all", daily), board("weekly", "all", weekly),
        board("daily", "python", language),
    ]}


class DigestTest(unittest.TestCase):
    def test_first_snapshot_is_baseline_even_on_rerun(self):
        today = snapshot("2026-11-15", [("a", 10)])
        result = trends.build_digest(today, {"a": {"first_seen": today["date"]}}, [today])
        self.assertTrue(result["is_baseline"])
        self.assertEqual(result["new_count"], 0)
        self.assertFalse(result["items"][0]["is_new"])

    def test_new_and_returning_repositories_are_distinct(self):
        today = snapshot("2026-11-15", [("new", 20), ("returning", 10)])
        repos = {"new": {"first_seen": today["date"]},
                 "returning": {"first_seen": "2026-11-01"}}
        result = trends.build_digest(today, repos, [snapshot("2026-11-14")])
        self.assertEqual(result["new_count"], 1)
        self.assertEqual([i["repo_key"] for i in result["items"] if i["is_new"]], ["new"])

    def test_cross_board_dedup_prefers_total_and_keeps_week_separate(self):
        today = snapshot("2026-11-15", [("a", 10)], [("a", 80)], [("a", 15)])
        today["boards"].reverse()
        result = trends.build_digest(today, {"a": {"first_seen": "2026-11-01"}})
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual((item["daily_stars"], item["weekly_stars"]), (10, 80))
        self.assertEqual(item["days_seen"], 1)
        self.assertEqual(item["reasons"], ["日增 Top 3", "周增 Top 3"])

    def test_seven_calendar_days_and_gaps(self):
        today = snapshot("2026-11-15", [("a", 1)])
        history = [snapshot("2026-11-" + day, [("a", 1)])
                   for day in ("08", "09", "10", "12", "14", "16")]
        result = trends.build_digest(today, {"a": {"first_seen": "2026-11-08"}}, history)
        item = result["items"][0]
        self.assertEqual(result["observed_days"], 5)
        self.assertEqual(item["days_seen"], 5)
        self.assertEqual(item["streak"], 2)
        self.assertIn("持续上榜", item["reasons"])

    def test_continuous_days_and_duplicate_snapshots(self):
        today = snapshot("2026-11-15", [("a", 1)])
        yesterday = snapshot("2026-11-14", [("a", 1)])
        history = [snapshot("2026-11-13", [("a", 1)]), yesterday, yesterday]
        item = trends.build_digest(today, {"a": {"first_seen": "2026-11-13"}}, history)["items"][0]
        self.assertEqual(item["days_seen"], 3)
        self.assertEqual(item["streak"], 3)

    def test_missing_growth_is_not_zero_or_a_hot_candidate(self):
        today = snapshot("2026-11-15", [("unknown", None), ("zero", 0)], [("w", 50)])
        repos = {key: {"first_seen": "2026-11-01"} for key in ("unknown", "zero", "w")}
        result = trends.build_digest(today, repos)
        self.assertEqual([i["repo_key"] for i in result["items"]], ["w"])
        self.assertIsNone(result["items"][0]["daily_stars"])

    def test_language_only_and_weekly_only_new_candidates(self):
        today = snapshot("2026-11-15", weekly=[("w", None)], language=[("p", None)])
        repos = {key: {"first_seen": today["date"]} for key in ("w", "p")}
        result = trends.build_digest(today, repos, [snapshot("2026-11-14")])
        self.assertEqual(result["new_count"], 2)
        self.assertEqual({i["repo_key"] for i in result["items"]}, {"w", "p"})

    def test_selection_is_bounded_deterministic_and_includes_each_signal(self):
        values = [("new" + str(i), i + 1) for i in range(12)]
        today = snapshot("2026-11-15", values + [("steady", 1)], [("weekly", 100)])
        repos = {key: {"first_seen": today["date"]} for key, _ in values}
        repos.update({key: {"first_seen": "2026-11-13"} for key in ("steady", "weekly")})
        history = [snapshot("2026-11-" + day, [("steady", 1)]) for day in ("13", "14")]
        result = trends.build_digest(today, repos, history)
        keys = [i["repo_key"] for i in result["items"]]
        self.assertEqual(len(keys), 8)
        self.assertEqual(len(set(keys)), 8)
        self.assertIn("new11", keys)
        self.assertIn("steady", keys)
        self.assertIn("weekly", keys)
        self.assertEqual(result, trends.build_digest(today, repos, history))

    def test_empty_boards_have_no_candidates(self):
        self.assertEqual(trends.build_digest(snapshot("2026-11-15"), {})["items"], [])


class HistoryTest(unittest.TestCase):
    def test_reads_only_baseline_and_recent_past(self):
        with tempfile.TemporaryDirectory() as directory:
            for date in ("2026-10-01", "2026-11-08", "2026-11-09", "2026-11-14", "2026-11-15", "2026-11-16"):
                year, month, _ = date.split("-")
                path = Path(directory, "snapshots", year, month, date + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(snapshot(date)), encoding="utf-8")
            history = trends.load_history(directory, "2026-11-15")
        self.assertEqual([s["date"] for s in history], ["2026-10-01", "2026-11-09", "2026-11-14"])

    def test_no_history(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(trends.load_history(directory, "2026-11-15"), [])
