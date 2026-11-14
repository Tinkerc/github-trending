# coding: utf-8
import unittest
from unittest import mock

import requests

import scraper
from tests.common import fixture

URL = "https://github.com/trending?since=daily"


class ParseBoardTest(unittest.TestCase):
    def test_daily_all_fields(self):
        board, metas = scraper.parse_board(fixture("daily_all.html"), "daily", "all", URL)
        self.assertEqual(board["period"], "daily")
        self.assertEqual(board["language_filter"], "all")
        self.assertEqual(board["source_url"], URL)
        self.assertEqual([e["rank"] for e in board["entries"]], [1, 2, 3])

        first = board["entries"][0]
        self.assertEqual(first["repo_key"], "example/project")
        self.assertEqual(first["stars"], 12345)
        self.assertEqual(first["forks"], 678)
        self.assertEqual(first["stars_in_period"], 321)

        meta = metas[0]
        self.assertEqual(meta["full_name"], "Example/Project")
        self.assertEqual(meta["url"], "https://github.com/Example/Project")
        self.assertEqual(meta["description"], "示例项目：结构化采集")
        self.assertEqual(meta["language"], "Python")

    def test_missing_fields_are_null(self):
        board, metas = scraper.parse_board(fixture("daily_all.html"), "daily", "all", URL)
        second = board["entries"][1]
        self.assertEqual(second["stars"], 1024)
        self.assertIsNone(second["forks"])
        self.assertIsNone(second["stars_in_period"])
        self.assertEqual(metas[1]["description"], "")
        self.assertIsNone(metas[1]["language"])

    def test_weekly_period_stars(self):
        board, _ = scraper.parse_board(
            fixture("weekly_all.html"), "weekly", "all",
            "https://github.com/trending?since=weekly",
        )
        self.assertEqual(board["entries"][0]["stars_in_period"], 1500)
        self.assertEqual(board["entries"][1]["stars_in_period"], 200)

    def test_empty_board_fails(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.parse_board(fixture("empty.html"), "daily", "all", URL)

    def test_duplicate_repo_fails(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.parse_board(fixture("duplicate.html"), "daily", "all", URL)

    def test_unparseable_number_fails(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.parse_board(fixture("bad_number.html"), "daily", "all", URL)

    def test_missing_link_fails(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.parse_board(fixture("missing_link.html"), "daily", "all", URL)


class ParseNumberTest(unittest.TestCase):
    def test_missing_is_none(self):
        for text in (None, "", "   "):
            self.assertIsNone(scraper.parse_count(text))

    def test_thousands_separator(self):
        self.assertEqual(scraper.parse_count("12,345"), 12345)
        self.assertEqual(scraper.parse_count(" 1,024 \n"), 1024)
        self.assertEqual(scraper.parse_count("0"), 0)

    def test_invalid_raises(self):
        for text in ("abc", "-5", "1.5", "12k"):
            with self.assertRaises(scraper.ScrapeError):
                scraper.parse_count(text)

    def test_period_stars(self):
        self.assertIsNone(scraper.parse_period_stars(None))
        self.assertIsNone(scraper.parse_period_stars("  "))
        self.assertEqual(scraper.parse_period_stars("321 stars today"), 321)
        self.assertEqual(scraper.parse_period_stars("1,500 stars this week"), 1500)
        with self.assertRaises(scraper.ScrapeError):
            scraper.parse_period_stars("stars today")


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FetchRetryTest(unittest.TestCase):
    def test_success_first_attempt(self):
        with mock.patch.object(
            scraper.requests, "get", return_value=FakeResponse(200, "ok")
        ) as get:
            self.assertEqual(scraper.fetch_board(URL), "ok")
        self.assertEqual(get.call_count, 1)

    def test_retry_on_429_then_success(self):
        responses = [FakeResponse(429), FakeResponse(200, "ok")]
        with mock.patch.object(scraper.requests, "get", side_effect=responses) as get, \
                mock.patch.object(scraper.time, "sleep") as sleep:
            self.assertEqual(scraper.fetch_board(URL), "ok")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_retry_on_connection_error(self):
        responses = [requests.ConnectionError("boom"), FakeResponse(200, "ok")]
        with mock.patch.object(scraper.requests, "get", side_effect=responses) as get, \
                mock.patch.object(scraper.time, "sleep"):
            self.assertEqual(scraper.fetch_board(URL), "ok")
        self.assertEqual(get.call_count, 2)

    def test_non_retryable_status_fails_immediately(self):
        with mock.patch.object(
            scraper.requests, "get", return_value=FakeResponse(404)
        ) as get, mock.patch.object(scraper.time, "sleep") as sleep:
            with self.assertRaises(scraper.ScrapeError):
                scraper.fetch_board(URL)
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_retry_exhaustion_fails(self):
        with mock.patch.object(
            scraper.requests, "get", return_value=FakeResponse(503)
        ) as get, mock.patch.object(scraper.time, "sleep") as sleep:
            with self.assertRaises(scraper.ScrapeError):
                scraper.fetch_board(URL)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


class BoardConfigTest(unittest.TestCase):
    def test_default_eight_boards(self):
        boards = scraper.configured_boards({})
        pairs = [(b["period"], b["language_filter"]) for b in boards]
        self.assertEqual(
            pairs,
            [("daily", "all"), ("weekly", "all")]
            + [("daily", lang) for lang in
               ("python", "javascript", "go", "html", "typescript", "java")],
        )
        self.assertEqual(boards[0]["url"], "https://github.com/trending?since=daily")
        self.assertEqual(boards[1]["url"], "https://github.com/trending?since=weekly")
        self.assertEqual(
            boards[2]["url"], "https://github.com/trending/python?since=daily"
        )

    def test_env_languages_normalized_and_deduped(self):
        boards = scraper.configured_boards(
            {"TRENDING_LANGUAGES": "Python, go ,python,,HTML,all"}
        )
        pairs = [(b["period"], b["language_filter"]) for b in boards]
        self.assertEqual(
            pairs,
            [("daily", "all"), ("weekly", "all"),
             ("daily", "python"), ("daily", "go"), ("daily", "html")],
        )

    def test_empty_env_uses_default(self):
        self.assertEqual(
            scraper.configured_boards({"TRENDING_LANGUAGES": "  "}),
            scraper.configured_boards({}),
        )


if __name__ == "__main__":
    unittest.main()