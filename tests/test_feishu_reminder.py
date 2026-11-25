import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import feishu_reminder as reminder

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/fake-hook"
SECRET = "fake-secret"


def quote_response(timestamp, price):
    quote = {
        "symbol": "XAU",
        "currency": "USD",
        "price": price,
        "updatedAt": timestamp.isoformat().replace("+00:00", "Z"),
    }
    return io.BytesIO(json.dumps(quote).encode())


class FeishuReminderTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {"FEISHU_WEBHOOK_URL": WEBHOOK, "FEISHU_SIGNING_SECRET": SECRET},
            )
        )
        self.quote_open = self.enterContext(
            mock.patch.object(reminder.request, "build_opener")
        ).return_value.open
        self.send = self.enterContext(mock.patch.object(reminder, "send"))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def run_reminder(self, *args):
        with mock.patch.object(sys, "argv", ["feishu_reminder.py", *map(str, args)]):
            return reminder.main()

    def sent_body(self):
        webhook, secret, payload = self.send.call_args.args
        self.assertEqual((webhook, secret), (WEBHOOK, SECRET))
        return payload["card"]["elements"][0]["text"]["content"]

    def test_broadcasts_save_and_compare_consecutive_quotes(self):
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        first_time = timestamp - timedelta(minutes=1)
        baseline = self.directory / "initial" / "quote.json"
        current = self.directory / "current" / "quote.json"

        for next_price, delta, percent, cny_price in [
            (3547.85, "+3.85", "+0.11", "763.83"),
            (3540.15, "-3.85", "-0.11", "762.17"),
        ]:
            with self.subTest(next_price=next_price):
                self.quote_open.reset_mock()
                self.quote_open.side_effect = [
                    quote_response(first_time, 3544),
                    quote_response(timestamp, next_price),
                ]

                self.assertEqual(
                    self.run_reminder("--slot", "hourly", "--save-quote", baseline),
                    0,
                )
                self.assertIn("暂无上次有效报价", self.sent_body())
                self.assertIn("**推算人民币金价** ≈ 763.00 元/克", self.sent_body())
                self.assertEqual(
                    json.loads(baseline.read_text()),
                    {
                        "symbol": "XAU",
                        "currency": "USD",
                        "price": "3544",
                        "updatedAt": first_time.isoformat(),
                    },
                )

                self.assertEqual(
                    self.run_reminder(
                        "--slot",
                        "hourly",
                        "--previous-quote",
                        baseline,
                        "--save-quote",
                        current,
                    ),
                    0,
                )
                body = self.sent_body()
                self.assertIn(f"{next_price:,.2f} 美元/金衡盎司", body)
                self.assertIn(f"**推算人民币金价** ≈ {cny_price} 元/克", body)
                self.assertIn(f"{delta} 美元/金衡盎司（{percent}%）", body)
                self.assertIn(
                    first_time.astimezone(reminder.SHANGHAI_TZ).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    body,
                )
                self.assertIn("6.6964", body)
                self.assertIn("含境内外金价差", body)
                self.assertEqual(
                    json.loads(current.read_text())["price"], str(next_price)
                )
                for call in self.quote_open.call_args_list:
                    self.assertEqual(call.args[0].full_url, reminder.GOLD_QUOTE_URL)
                    self.assertEqual(call.kwargs["timeout"], 8)

    def test_old_or_duplicate_quotes_do_not_replace_baseline(self):
        timestamp = datetime.now(timezone.utc)
        baseline = self.directory / "quote.json"
        previous = quote_response(timestamp - timedelta(minutes=1), 3544).getvalue()
        baseline.write_bytes(previous)

        for age_minutes in (1, 2, 6):
            with self.subTest(age_minutes=age_minutes):
                self.quote_open.return_value = quote_response(
                    timestamp - timedelta(minutes=age_minutes), 3547.85
                )

                self.assertEqual(
                    self.run_reminder(
                        "--slot",
                        "hourly",
                        "--previous-quote",
                        baseline,
                        "--save-quote",
                        baseline,
                    ),
                    0,
                )
                self.assertIn("暂不计算涨跌", self.sent_body())
                self.assertEqual(baseline.read_bytes(), previous)

    def test_reminder_still_sends_when_quote_fails(self):
        self.quote_open.side_effect = TimeoutError("source offline")
        output = self.directory / "quote.json"

        self.assertEqual(
            self.run_reminder("--slot", "hourly", "--save-quote", output), 0
        )

        body = self.sent_body()
        self.assertIn("伦敦金行情暂不可用", body)
        self.assertNotIn("推算人民币金价", body)
        self.assertIn("6.6964", body)
        self.assertFalse(output.exists())
        self.quote_open.assert_called_once()

    def test_manual_test_reads_previous_quote_without_saving(self):
        timestamp = datetime.now(timezone.utc)
        baseline = self.directory / "previous.json"
        baseline.write_bytes(
            quote_response(timestamp - timedelta(minutes=1), 3544).getvalue()
        )
        output = self.directory / "quote.json"
        self.quote_open.return_value = quote_response(timestamp, 3547.85)

        self.assertEqual(
            self.run_reminder(
                "--slot", "test", "--previous-quote", baseline, "--save-quote", output
            ),
            0,
        )

        body = self.sent_body()
        self.assertIn("+0.11%", body)
        self.assertIn("每小时第 17 分钟", body)
        payload = self.send.call_args.args[2]
        self.assertEqual(payload["card"]["header"]["title"]["content"], "黄金小时播报｜测试")
        self.assertFalse(output.exists())

    def test_snapshot_survives_feishu_failure(self):
        self.quote_open.return_value = quote_response(
            datetime.now(timezone.utc), 3547.85
        )
        self.send.side_effect = ValueError("bot rejected")
        output = self.directory / "quote.json"

        self.assertEqual(
            self.run_reminder("--slot", "hourly", "--save-quote", output), 1
        )

        self.assertEqual(json.loads(output.read_text())["price"], "3547.85")

    def test_dry_run_does_not_fetch_quotes(self):
        self.assertEqual(self.run_reminder("--slot", "hourly", "--dry-run"), 0)

        payload = json.loads(self.stdout.getvalue())
        body = payload["card"]["elements"][0]["text"]["content"]
        self.assertEqual(payload["card"]["header"]["title"]["content"], "黄金小时播报")
        self.assertIn("6.6964", body)
        self.quote_open.assert_not_called()
        self.send.assert_not_called()
