# coding: utf-8
"""从 JSON 快照计算精选理由，不抓取页面或发送通知。"""

import datetime
import json
from pathlib import Path

TOP_N = 8


def load_history(data_dir, date):
    """读取此前六天及最早快照；最早日期用于识别首次采集基线。"""
    start = (datetime.date.fromisoformat(date) - datetime.timedelta(days=6)).isoformat()
    paths = sorted(
        path for path in Path(data_dir, "snapshots").glob("*/*/*.json")
        if path.stem < date
    )
    selected = [path for path in paths if path.stem >= start]
    if paths and paths[0] not in selected:
        selected.insert(0, paths[0])
    history = []
    for path in selected:
        with path.open(encoding="utf-8") as handle:
            history.append(json.load(handle))
    return history


def _entries(snapshot, period):
    """同仓库只取一次，总榜指标优先，不累加跨榜数值。"""
    entries = {}
    boards = sorted(snapshot["boards"], key=lambda b: b["language_filter"] != "all")
    for board in boards:
        if board["period"] != period:
            continue
        if period == "weekly" and board["language_filter"] != "all":
            continue
        for entry in board["entries"]:
            entries.setdefault(entry["repo_key"], entry)
    return entries


def build_digest(snapshot, repositories, history=()):
    date = snapshot["date"]
    today = datetime.date.fromisoformat(date)
    start = (today - datetime.timedelta(days=6)).isoformat()
    prior = {s["date"]: s for s in history if s["date"] < date}
    baseline = min(prior, default=date)
    window = {day: s for day, s in prior.items() if day >= start}
    window[date] = snapshot
    daily = _entries(snapshot, "daily")
    weekly = _entries(snapshot, "weekly")
    appearances = {}
    for day, observed in window.items():
        for key in _entries(observed, "daily"):
            appearances.setdefault(key, set()).add(day)

    items = {}
    for key in daily.keys() | weekly.keys():
        days = appearances.get(key, set())
        streak = 0
        cursor = today
        while cursor.isoformat() in days:
            streak += 1
            cursor -= datetime.timedelta(days=1)
        items[key] = {
            "repo_key": key,
            "daily_stars": daily.get(key, {}).get("stars_in_period"),
            "weekly_stars": weekly.get(key, {}).get("stars_in_period"),
            "is_new": baseline < date and repositories[key]["first_seen"] == date,
            "days_seen": len(days),
            "streak": streak,
            "reasons": [],
        }

    def growth_order(key):
        item = items[key]
        return (-(item["daily_stars"] or 0), -(item["weekly_stars"] or 0), key)

    hot = sorted(
        (key for key in daily if (items[key]["daily_stars"] or 0) > 0),
        key=growth_order,
    )[:3]
    new = sorted((key for key in items if items[key]["is_new"]), key=growth_order)
    sustained = sorted(
        (key for key in daily if items[key]["days_seen"] >= 3),
        key=lambda key: (-items[key]["days_seen"], -items[key]["streak"], growth_order(key)),
    )
    week_hot = sorted(
        (key for key in weekly if (items[key]["weekly_stars"] or 0) > 0),
        key=lambda key: (-items[key]["weekly_stars"], key),
    )[:3]
    queues = (hot, new, sustained, week_hot)
    for keys, reason in zip(queues, ("日增 Top 3", "首次发现", "持续上榜", "周增 Top 3")):
        for key in keys:
            items[key]["reasons"].append(reason)

    # 各种信号轮流获得展示位置，重复仓库只占一条。
    selected = []
    positions = [0] * len(queues)
    while len(selected) < TOP_N:
        added = False
        for index, queue in enumerate(queues):
            while positions[index] < len(queue):
                key = queue[positions[index]]
                positions[index] += 1
                if key not in selected:
                    selected.append(key)
                    added = True
                    break
            if len(selected) == TOP_N:
                break
        if not added:
            break
    return {
        "date": date,
        "is_baseline": baseline == date,
        "observed_days": len(window),
        "new_count": len(new),
        "items": [items[key] for key in selected],
    }
