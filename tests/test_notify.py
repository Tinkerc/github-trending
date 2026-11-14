# coding: utf-8
import contextlib
import io
import json
import unittest
from unittest import mock

import requests

import notify
import scraper
from tests.common import fixture

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/secret-token-abc123"
SECRET = "test-secret"


def make_snapshot_and_repos():
    boards = []
    metas_by_board = []
    for name, period, lang in (
        ("daily_all.html", "daily", "all"),
        ("weekly_all.html", "weekly", "all"),
        ("python_daily.html", "daily", "python"),
    ):
        board, metas = scraper.parse_board(
            fixture(name), period, lang, scraper.board_url(period, lang)
        )
        boards.append(board)
        metas_by_board.append(metas)
    repos_doc = scraper.merge_repositories(
        {"schema_version": 1, "repositories": {}}, metas_by_board, "2026-11-15"
    )
    snapshot = {
        "schema_version": 1,
        "date": "2026-11-15",
        "timezone": "Asia/Shanghai",
        "fetched_at": "2026-11-15T02:00:12Z",
        "boards": boards,
    }
    return snapshot, repos_doc["repositories"]


class SignTest(unittest.TestCase):
    def test_fixed_vector(self):
        self.assertEqual(
            notify.sign("1700000000", SECRET),
            "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84=",
        )


class BuildPayloadTest(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.repos = make_snapshot_and_repos()

    def test_no_secret_no_sign_fields(self):
        payload = notify.build_payload(self.snapshot, self.repos)
        self.assertEqual(payload["msg_type"], "text")
        self.assertNotIn("timestamp", payload)
        self.assertNotIn("sign", payload)

    def test_with_secret_dynamic_fields(self):
        payload = notify.build_payload(
            self.snapshot, self.repos, signing_secret=SECRET, timestamp=1700000000
        )
        self.assertEqual(payload["timestamp"], "1700000000")
        self.assertEqual(
            payload["sign"], "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84="
        )

    def test_text_content(self):
        text = notify.build_text(
            self.snapshot, self.repos, archive_url="https://example.com/archive.json"
        )
        self.assertIn("GitHub Trending 2026-11-15", text)
        self.assertIn("总榜日榜", text)
        self.assertIn("总榜周榜", text)
        self.assertIn("Example/Project +321", text)
        self.assertIn("https://github.com/Example/Project", text)
        self.assertIn("归档: https://example.com/archive.json", text)
        self.assertNotIn("py-only/Lib", text)

    def test_body_under_limit_and_reduces_entries(self):
        snapshot, repos = make_snapshot_and_repos()
        long_name = "org/" + "x" * 300
        key = long_name.lower()
        repos[key] = {
            "full_name": long_name,
            "url": "https://github.com/" + long_name,
            "description": "",
            "language": None,
            "first_seen": "2026-11-15",
            "last_seen": "2026-11-15",
        }
        snapshot["boards"][0]["entries"] = [
            {"rank": i, "repo_key": key, "stars": i, "forks": 0, "stars_in_period": i}
            for i in range(1, 41)
        ]
        payload = notify.build_payload(snapshot, repos, top_n=40)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertLess(len(body), notify.MAX_BODY_BYTES)
        self.assertLess(payload["content"]["text"].count("https://github.com/"), 40)

    def test_chinese_utf8_bytes(self):
        payload = notify.build_payload(self.snapshot, self.repos)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertIn("总榜日榜".encode("utf-8"), body)
        self.assertLess(len(body), notify.MAX_BODY_BYTES)


class FakePostResponse:
    def __init__(self, result=None, http_error=None):
        self._result = result
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise self._http_error

    def json(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class SendTest(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.repos = make_snapshot_and_repos()
        self.payload = notify.build_payload(self.snapshot, self.repos)

    def test_success_checks_code_zero(self):
        response = FakePostResponse(result={"code": 0, "msg": "success"})
        with mock.patch.object(notify.requests, "post", return_value=response) as post:
            notify.send(WEBHOOK, self.payload)
        self.assertEqual(post.call_count, 1)
        args, kwargs = post.call_args
        self.assertEqual(args[0], WEBHOOK)
        self.assertEqual(
            kwargs["data"], json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
        )
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_business_failure_raises(self):
        response = FakePostResponse(result={"code": 19021, "msg": "sign match fail"})
        with mock.patch.object(notify.requests, "post", return_value=response):
            with self.assertRaises(notify.NotifyError) as ctx:
                notify.send(WEBHOOK, self.payload)
        self.assertIn("19021", str(ctx.exception))
        self.assertNotIn(WEBHOOK, str(ctx.exception))

    def test_http_error_hides_url(self):
        response = FakePostResponse(
            http_error=requests.HTTPError("403 Client Error for url: " + WEBHOOK)
        )
        with mock.patch.object(notify.requests, "post", return_value=response):
            with self.assertRaises(notify.NotifyError) as ctx:
                notify.send(WEBHOOK, self.payload)
        self.assertNotIn("secret-token", str(ctx.exception))

    def test_connection_error_hides_url(self):
        error = requests.ConnectionError("failed to connect " + WEBHOOK)
        with mock.patch.object(notify.requests, "post", side_effect=error):
            with self.assertRaises(notify.NotifyError) as ctx:
                notify.send(WEBHOOK, self.payload)
        self.assertNotIn("secret-token", str(ctx.exception))
        self.assertIn("ConnectionError", str(ctx.exception))

    def test_invalid_json_response(self):
        response = FakePostResponse(result=ValueError("not json"))
        with mock.patch.object(notify.requests, "post", return_value=response):
            with self.assertRaises(notify.NotifyError):
                notify.send(WEBHOOK, self.payload)


class SendNotificationTest(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.repos = make_snapshot_and_repos()

    def test_no_webhook_skips(self):
        output = io.StringIO()
        with mock.patch.object(notify.requests, "post") as post, \
                contextlib.redirect_stdout(output):
            sent = notify.send_notification(self.snapshot, self.repos, webhook_url=None)
        self.assertFalse(sent)
        post.assert_not_called()
        self.assertIn("跳过", output.getvalue())

    def test_webhook_sent(self):
        response = FakePostResponse(result={"code": 0, "msg": "success"})
        with mock.patch.object(notify.requests, "post", return_value=response) as post:
            sent = notify.send_notification(
                self.snapshot, self.repos, webhook_url=WEBHOOK, signing_secret=SECRET
            )
        self.assertTrue(sent)
        payload = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertIn("timestamp", payload)
        self.assertIn("sign", payload)

    def test_failure_logs_no_sensitive_info(self):
        error = requests.ConnectionError("failed to connect " + WEBHOOK)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(notify.requests, "post", side_effect=error), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(notify.NotifyError) as ctx:
                notify.send_notification(
                    self.snapshot, self.repos,
                    webhook_url=WEBHOOK, signing_secret=SECRET,
                )
        combined = stdout.getvalue() + stderr.getvalue() + str(ctx.exception)
        self.assertNotIn("secret-token", combined)
        self.assertNotIn(SECRET, combined)
        self.assertNotIn(WEBHOOK, combined)


if __name__ == "__main__":
    unittest.main()