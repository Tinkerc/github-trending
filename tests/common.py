# coding: utf-8
import datetime
import os

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
UTC_NOW = datetime.datetime(2026, 11, 15, 2, 0, 12, tzinfo=datetime.timezone.utc)


def fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return handle.read()