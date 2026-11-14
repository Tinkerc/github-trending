# coding: utf-8
import contextlib
import datetime
import io
import os
import tempfile
import unittest
from unittest import mock

import notify
import scraper
from tests.test_storage import default_mapping, run_with_mapping


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = self.tmp.name

    def test_normal_run_does_not_notify(self):
        mapping = default_mapping()

        def fake_fetch(url, **kwargs):
            return mapping[url]

        with mock.patch.object(
            notify, "send", side_effect=AssertionError("普通采集不应发送通知")
        ) as send, mock.patch.object(
            scraper, "fetch_board", side_effect=fake_fetch
        ), mock.patch.dict(os.environ, {}, clear=True):
            code = scraper.main(["--data-dir", self.data_dir])
        self.assertEqual(code, 0)
        send.assert_not_called()
        self.assertTrue(
            os.path.exists(os.path.join(self.data_dir, "repos.json"))
        )

    def test_notify_only_does_not_fetch(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        run_with_mapping(self.data_dir, default_mapping(), now=now)

        response = mock.Mock()
        response.json.return_value = {"code": 0, "msg": "success"}
        with mock.patch.object(
            scraper, "fetch_board", side_effect=AssertionError("--notify-only 不应抓取")
        ) as fetch, mock.patch.object(
            notify.requests, "post", return_value=response
        ) as post, mock.patch.dict(
            os.environ, {"FEISHU_WEBHOOK_URL": "https://example.com/hook"}, clear=True
        ):
            code = scraper.main(["--notify-only", "--data-dir", self.data_dir])
        self.assertEqual(code, 0)
        fetch.assert_not_called()
        self.assertEqual(post.call_count, 1)

    def test_notify_only_requires_snapshot(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stderr(stderr):
            code = scraper.main(["--notify-only", "--data-dir", self.data_dir])
        self.assertEqual(code, 1)
        self.assertIn("快照不存在", stderr.getvalue())

    def test_notify_explicit_date_after_midnight(self):
        before_midnight = datetime.datetime(
            2026, 11, 15, 15, 59, 59, tzinfo=datetime.timezone.utc
        )
        run_with_mapping(self.data_dir, default_mapping(), now=before_midnight)
        after_midnight = before_midnight + datetime.timedelta(seconds=2)
        with mock.patch.object(scraper.datetime, "datetime") as clock, \
                mock.patch.object(notify, "send_notification") as send, \
                mock.patch.object(scraper, "fetch_board") as fetch:
            clock.now.return_value = after_midnight
            code = scraper.main([
                "--notify-only", "--date", "2026-11-15",
                "--data-dir", self.data_dir,
            ])
        self.assertEqual(code, 0)
        self.assertEqual(send.call_args.args[0]["date"], "2026-11-15")
        fetch.assert_not_called()

    def test_scrape_exports_snapshot_date(self):
        output_path = os.path.join(self.data_dir, "github-output")
        with mock.patch.object(
            scraper, "run_scrape", return_value={"date": "2026-11-15", "boards": []}
        ), mock.patch.dict(os.environ, {"GITHUB_OUTPUT": output_path}, clear=True):
            self.assertEqual(scraper.main([]), 0)
        with open(output_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "date=2026-11-15\n")

    def test_invalid_notification_date_rejected(self):
        for date in ("2026-02-30", "../2026-11-15", "20261115"):
            with self.subTest(date=date), contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(notify, "send_notification") as send, \
                    self.assertRaises(SystemExit) as error:
                scraper.main(["--notify-only", "--date", date])
            self.assertEqual(error.exception.code, 2)
            send.assert_not_called()

    def test_date_without_notify_only_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(scraper, "run_scrape") as scrape, \
                self.assertRaises(SystemExit) as error:
            scraper.main(["--date", "2026-11-15"])
        self.assertEqual(error.exception.code, 2)
        scrape.assert_not_called()

    def test_scrape_failure_exit_code(self):
        stderr = io.StringIO()
        with mock.patch.object(
            scraper, "fetch_board", side_effect=scraper.ScrapeError("模拟失败")
        ), mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stderr(stderr):
            code = scraper.main(["--data-dir", self.data_dir])
        self.assertEqual(code, 1)
        self.assertIn("模拟失败", stderr.getvalue())

    def test_archive_url_from_github_env(self):
        with mock.patch.dict(
            os.environ,
            {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_REF_NAME": "main"},
            clear=True,
        ):
            url = scraper.archive_url("data", "2026-11-15")
        self.assertEqual(
            url,
            "https://github.com/owner/repo/blob/main/data/snapshots/2026/11/2026-11-15.json",
        )

    def test_archive_url_absent_without_repo_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(scraper.archive_url("data", "2026-11-15"))


if __name__ == "__main__":
    unittest.main()
