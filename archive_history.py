"""将年份目录中的历史 Markdown 提取到 data/history，不移动原文件。"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DATE_HEADER = re.compile(r"^#{2,3}\s*(\d{4}-\d{2}-\d{2})\s*$")
LANGUAGE_HEADER = re.compile(r"^####\s*([\w+#.-]+)\s*$")
ENTRY = re.compile(
    r"^\*\s+(?:<img\b[^>]*>\s*)?\[([^\]]*)\]"
    r"\(\s*([^\s)]+)\s*\)\s*:(.*)$"
)


def parse_markdown(path, source_root):
    """返回快照和逐条元数据，保留简介中的换行和原始记录顺序。"""
    date = datetime.date.fromisoformat(path.stem).isoformat()
    if date != path.stem or path.parent.name != date[:4]:
        raise ValueError(f"{path}: 文件日期与年份目录不符")
    raw = path.read_bytes()
    boards = []
    metas = []
    current_entry = None
    description_lines = []
    header_seen = False

    def finish_description():
        if current_entry is not None:
            description = "\n".join(description_lines).strip()
            current_entry["description"] = description
            metas[-1]["description"] = description

    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        date_match = DATE_HEADER.fullmatch(line)
        language_match = LANGUAGE_HEADER.fullmatch(line)
        entry_match = ENTRY.fullmatch(line)
        if date_match:
            if date_match[1] != date or header_seen or boards:
                raise ValueError(f"{path}:{line_number}: 正文日期不符或日期标题重复")
            header_seen = True
        elif language_match:
            if not header_seen:
                raise ValueError(f"{path}:{line_number}: 榜单之前缺少日期标题")
            finish_description()
            current_entry = None
            language = language_match[1].lower()
            if any(board["language_filter"] == language for board in boards):
                raise ValueError(f"{path}:{line_number}: 语言榜单重复: {language}")
            boards.append({
                "period": "daily",
                "language_filter": language,
                "source_url": f"https://github.com/trending/{language}?since=daily",
                "entries": [],
            })
        elif entry_match:
            if not boards:
                raise ValueError(f"{path}:{line_number}: 条目之前缺少语言标题")
            finish_description()
            name, url, description = entry_match.groups()
            parsed = urlsplit(url)
            if (parsed.scheme not in ("http", "https")
                    or parsed.netloc.lower() != "github.com"
                    or not re.fullmatch(r"/[^/\s?#]+/[^/\s?#]+/?", parsed.path)
                    or parsed.query or parsed.fragment):
                raise ValueError(f"{path}:{line_number}: 无效仓库链接: {url}")
            full_name = parsed.path.strip("/")
            repo_key = full_name.lower()
            current_entry = {
                "rank": len(boards[-1]["entries"]) + 1,
                "repo_key": repo_key,
                "name": name,
                "url": url,
                "source_line": line_number,
                "stars": None,
                "forks": None,
                "stars_in_period": None,
            }
            boards[-1]["entries"].append(current_entry)
            metas.append({
                "repo_key": repo_key,
                "full_name": full_name,
                "url": url,
                "language": None,
            })
            description_lines = [description]
        elif re.match(r"^\*\s+", line):
            raise ValueError(f"{path}:{line_number}: 无法识别 Markdown 条目")
        elif current_entry is not None:
            description_lines.append(line)
        elif line.strip():
            raise ValueError(f"{path}:{line_number}: 无法识别的榜单内容")
    finish_description()
    if not header_seen:
        raise ValueError(f"{path}: 缺少日期标题")
    return {
        "schema_version": 1,
        "date": date,
        "timezone": "Asia/Shanghai",
        "fetched_at": None,
        "source_type": "historical_markdown",
        "source_file": path.relative_to(source_root).as_posix(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "boards": boards,
    }, metas


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def archive_history(source_dir, data_dir):
    source_dir = Path(source_dir).resolve()
    archive_dir = Path(data_dir).resolve() / "history"
    files = sorted(
        path for directory in source_dir.iterdir()
        if directory.is_dir() and re.fullmatch(r"\d{4}", directory.name)
        for path in directory.glob("*.md")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)
    )
    if not files:
        raise ValueError(f"{source_dir}: 没有找到 YYYY/YYYY-MM-DD.md")
    snapshots = []
    repositories = {}
    board_count = entry_count = 0
    # 全部解析通过后才写入，避免格式错误留下部分归档。
    for path in files:
        snapshot, metas = parse_markdown(path, source_dir)
        snapshots.append(snapshot)
        date = snapshot["date"]
        board_count += len(snapshot["boards"])
        entry_count += len(metas)
        for meta in metas:
            key = meta["repo_key"]
            existing = repositories.get(key)
            repositories[key] = {
                field: value for field, value in meta.items() if field != "repo_key"
            }
            repositories[key].update({
                "first_seen": existing["first_seen"] if existing else date,
                "last_seen": date,
            })
    manifest = {
        "schema_version": 1,
        "source_type": "historical_markdown",
        "files": len(files),
        "boards": board_count,
        "entries": entry_count,
        "repositories": len(repositories),
        "empty_files": sum(not snapshot["boards"] for snapshot in snapshots),
        "first_date": snapshots[0]["date"],
        "last_date": snapshots[-1]["date"],
    }
    write_json(archive_dir / "repos.json", {
        "schema_version": 1, "repositories": repositories,
    })
    for snapshot in snapshots:
        date = snapshot["date"]
        write_json(
            archive_dir / "snapshots" / date[:4] / date[5:7] / f"{date}.json",
            snapshot,
        )
    write_json(archive_dir / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT, help="历史年份目录所在根目录")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="输出根目录，归档写入其 history 子目录")
    args = parser.parse_args(argv)
    try:
        manifest = archive_history(args.source_dir, args.data_dir)
    except (OSError, ValueError) as exc:
        print(f"归档失败: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"已归档至 {args.data_dir.resolve() / 'history'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
