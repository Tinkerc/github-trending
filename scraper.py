# coding: utf-8
"""GitHub Trending 采集：抓取榜单、校验并写入 JSON 数据。

普通运行只生成数据，不发送通知；``--notify-only`` 从指定日期（默认当天）快照发送通知。
Git 提交与推送由 GitHub Actions 负责。
"""

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

import requests
from pyquery import PyQuery as pq

import notify
import trends

SCHEMA_VERSION = 1
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_LANGUAGES = ("python", "javascript", "go", "html", "typescript", "java")
TRENDING_BASE_URL = "https://github.com/trending"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) "
        "Gecko/20100101 Firefox/132.0"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.5",
}
TIMEOUT = (10, 30)
MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
REPO_PATH_RE = re.compile(r"^/[^/\s]+/[^/\s]+$")
NUMBER_RE = re.compile(r"^\d+$")
PERIOD_STARS_RE = re.compile(r"([\d,]+)\s+stars?\b")


class ScrapeError(Exception):
    """抓取、解析或校验失败。"""


def shanghai_date(now_utc):
    return now_utc.astimezone(SHANGHAI).date().isoformat()


def configured_boards(environ=None):
    """返回固定顺序的榜单配置：总榜 daily/weekly + 各语言 daily。"""
    environ = os.environ if environ is None else environ
    raw = environ.get("TRENDING_LANGUAGES", "")
    languages = []
    for part in raw.split(",") if raw.strip() else DEFAULT_LANGUAGES:
        slug = part.strip().lower()
        if slug and slug != "all" and slug not in languages:
            languages.append(slug)
    boards = [("daily", "all"), ("weekly", "all")]
    boards.extend(("daily", slug) for slug in languages)
    return [
        {"period": period, "language_filter": lang, "url": board_url(period, lang)}
        for period, lang in boards
    ]


def board_url(period, language_filter):
    if language_filter == "all":
        return "{base}?since={period}".format(base=TRENDING_BASE_URL, period=period)
    return "{base}/{lang}?since={period}".format(
        base=TRENDING_BASE_URL, lang=language_filter, period=period
    )


def fetch_board(url, max_attempts=MAX_ATTEMPTS):
    """带有限重试与退避的抓取；重试耗尽或不可重试错误直接失败。"""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = type(exc).__name__
        else:
            if response.status_code == 200:
                return response.text
            if response.status_code not in RETRY_STATUS:
                raise ScrapeError(
                    "抓取失败 HTTP {status}: {url}".format(
                        status=response.status_code, url=url
                    )
                )
            last_error = "HTTP {status}".format(status=response.status_code)
        if attempt < max_attempts:
            time.sleep(2 ** (attempt - 1))
    raise ScrapeError(
        "抓取失败（已重试 {n} 次，最后错误 {err}）: {url}".format(
            n=max_attempts, err=last_error, url=url
        )
    )


def parse_count(text):
    """解析累计数值：缺失/空白为 None；非空但无法解析时报错。"""
    if text is None:
        return None
    stripped = re.sub(r"[\s,]", "", text)
    if not stripped:
        return None
    if not NUMBER_RE.match(stripped):
        raise ScrapeError("无法解析数值: {text!r}".format(text=text))
    return int(stripped)


def parse_period_stars(text):
    if text is None or not text.strip():
        return None
    match = PERIOD_STARS_RE.search(text)
    if not match:
        raise ScrapeError("无法解析周期增长: {text!r}".format(text=text))
    return int(match.group(1).replace(",", ""))


def _selection_text(item, selector):
    node = item(selector)
    return node.text() if len(node) else None


def parse_board(html, period, language_filter, source_url):
    """解析单个榜单页面，返回 (board, 元数据列表)。结构异常直接失败。"""
    document = pq(html)
    articles = document("article.Box-row")
    if not len(articles):
        raise ScrapeError("空榜或页面结构异常: {url}".format(url=source_url))
    entries = []
    metas = []
    seen = set()
    for rank, node in enumerate(articles, start=1):
        item = pq(node)
        href = item("h2 a").attr("href")
        if not href or not REPO_PATH_RE.match(href.strip()):
            raise ScrapeError(
                "第 {rank} 条缺少有效仓库链接: {url}".format(rank=rank, url=source_url)
            )
        full_name = href.strip().lstrip("/")
        repo_key = full_name.lower()
        if repo_key in seen:
            raise ScrapeError(
                "榜单内仓库重复 {key}: {url}".format(key=repo_key, url=source_url)
            )
        seen.add(repo_key)
        language = _selection_text(item, "[itemprop='programmingLanguage']")
        entries.append(
            {
                "rank": rank,
                "repo_key": repo_key,
                "stars": parse_count(_selection_text(item, "a[href$='/stargazers']")),
                "forks": parse_count(_selection_text(item, "a[href$='/forks']")),
                "stars_in_period": parse_period_stars(
                    _selection_text(item, "span.float-sm-right")
                ),
            }
        )
        metas.append(
            {
                "repo_key": repo_key,
                "full_name": full_name,
                "url": "https://github.com/" + full_name,
                "description": (_selection_text(item, "p.col-9") or "").strip(),
                "language": language.strip() if language and language.strip() else None,
            }
        )
    board = {
        "period": period,
        "language_filter": language_filter,
        "source_url": source_url,
        "entries": entries,
    }
    return board, metas


def validate_snapshot(snapshot, repositories):
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ScrapeError("快照 schema_version 不符")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", snapshot.get("date", "")):
        raise ScrapeError("快照日期格式不符")
    boards = snapshot.get("boards") or []
    if not boards:
        raise ScrapeError("快照缺少榜单")
    board_keys = set()
    for board in boards:
        key = (board["period"], board["language_filter"])
        if key in board_keys:
            raise ScrapeError("榜单重复: {key}".format(key=key))
        board_keys.add(key)
        seen = set()
        for rank, entry in enumerate(board["entries"], start=1):
            if entry["rank"] != rank:
                raise ScrapeError("排名不连续: {key}".format(key=key))
            repo_key = entry["repo_key"]
            if repo_key in seen:
                raise ScrapeError("榜单内仓库重复: {key}".format(key=key))
            seen.add(repo_key)
            if repo_key not in repositories:
                raise ScrapeError("快照引用了目录中不存在的仓库: {k}".format(k=repo_key))
            for field in ("stars", "forks", "stars_in_period"):
                value = entry[field]
                if value is not None and (not isinstance(value, int) or value < 0):
                    raise ScrapeError("非法数值 {f}: {v!r}".format(f=field, v=value))


def load_repositories(data_dir):
    path = os.path.join(data_dir, "repos.json")
    if not os.path.exists(path):
        return {"schema_version": SCHEMA_VERSION, "repositories": {}}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def merge_repositories(repos_doc, metas_by_board, date):
    """按固定榜单顺序合并元数据；保留 first_seen 与不再上榜的条目。"""
    repositories = repos_doc["repositories"]
    for metas in metas_by_board:
        for meta in metas:
            key = meta["repo_key"]
            existing = repositories.get(key)
            repositories[key] = {
                "full_name": meta["full_name"],
                "url": meta["url"],
                "description": meta["description"],
                "language": meta["language"],
                "first_seen": existing["first_seen"] if existing else date,
                "last_seen": date,
            }
    return repos_doc


def snapshot_rel_path(date):
    """快照相对 data_dir 的路径。"""
    year, month, _ = date.split("-")
    return os.path.join("snapshots", year, month, date + ".json")


def atomic_write_json(path, document):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def save_run(data_dir, boards_with_metas, date, fetched_at):
    """全部榜单校验通过后落盘：先原子替换仓库目录，再替换快照。"""
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        "timezone": "Asia/Shanghai",
        "fetched_at": fetched_at,
        "boards": [board for board, _ in boards_with_metas],
    }
    repos_doc = load_repositories(data_dir)
    merge_repositories(repos_doc, [metas for _, metas in boards_with_metas], date)
    validate_snapshot(snapshot, repos_doc["repositories"])
    atomic_write_json(os.path.join(data_dir, "repos.json"), repos_doc)
    atomic_write_json(os.path.join(data_dir, snapshot_rel_path(date)), snapshot)
    return snapshot


def run_scrape(data_dir, now_utc=None):
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    date = shanghai_date(now_utc)
    fetched_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []
    for config in configured_boards():
        html = fetch_board(config["url"])
        results.append(
            parse_board(
                html, config["period"], config["language_filter"], config["url"]
            )
        )
    return save_run(data_dir, results, date, fetched_at)


def archive_url(data_dir, date):
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    ref = os.environ.get("GITHUB_REF_NAME", "HEAD")
    rel = "/".join([data_dir.rstrip("/")] + snapshot_rel_path(date).split(os.sep))
    return "{server}/{repo}/blob/{ref}/{path}".format(
        server=server, repo=repository, ref=ref, path=rel
    )


def run_notify_only(data_dir, date=None):
    date = date or shanghai_date(datetime.datetime.now(datetime.timezone.utc))
    path = os.path.join(data_dir, snapshot_rel_path(date))
    if not os.path.exists(path):
        raise ScrapeError("快照不存在，无法通知: {p}".format(p=path))
    with open(path, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    repos_doc = load_repositories(data_dir)
    validate_snapshot(snapshot, repos_doc["repositories"])
    digest = trends.build_digest(
        snapshot, repos_doc["repositories"], trends.load_history(data_dir, date)
    )
    notify.send_notification(
        snapshot,
        repos_doc["repositories"],
        webhook_url=os.environ.get("FEISHU_WEBHOOK_URL"),
        signing_secret=os.environ.get("FEISHU_SIGNING_SECRET"),
        archive_url=archive_url(data_dir, date),
        digest=digest,
    )


def notification_date(value):
    try:
        date = datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("日期必须为有效的 YYYY-MM-DD") from None
    if date.isoformat() != value:
        raise argparse.ArgumentTypeError("日期必须为有效的 YYYY-MM-DD")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="GitHub Trending JSON 采集")
    parser.add_argument(
        "--data-dir", default="data", help="数据目录（默认 data）"
    )
    parser.add_argument(
        "--notify-only",
        action="store_true",
        help="不抓取，仅从已保存快照发送飞书通知（默认当天）",
    )
    parser.add_argument(
        "--date", type=notification_date, help="通知快照日期 YYYY-MM-DD，仅用于 --notify-only"
    )
    args = parser.parse_args(argv)
    if args.date and not args.notify_only:
        parser.error("--date 仅用于 --notify-only")
    try:
        if args.notify_only:
            run_notify_only(args.data_dir, args.date)
        else:
            snapshot = run_scrape(args.data_dir)
            output_path = os.environ.get("GITHUB_OUTPUT")
            if output_path:
                with open(output_path, "a", encoding="utf-8") as handle:
                    handle.write("date={date}\n".format(date=snapshot["date"]))
            print(
                "已归档 {date}，{n} 个榜单".format(
                    date=snapshot["date"], n=len(snapshot["boards"])
                )
            )
    except (ScrapeError, notify.NotifyError) as exc:
        print("失败: {msg}".format(msg=exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
