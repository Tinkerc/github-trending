"""按年份压缩归档历史 Markdown，保留原文件，不核对内容哈希。"""

import argparse
import os
from pathlib import Path
import re
import tempfile
import zipfile


def archive_markdown(source_dir, data_dir):
    source_dir = Path(source_dir).resolve()
    output_dir = Path(data_dir).resolve() / "history" / "markdown"
    archives = files = 0
    for directory in sorted(source_dir.iterdir()):
        if not directory.is_dir() or not re.fullmatch(r"\d{4}", directory.name):
            continue
        markdown_files = sorted(directory.glob("*.md"))
        if not markdown_files:
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{directory.name}.zip"
        fd, temporary = tempfile.mkstemp(dir=output_dir, prefix=".tmp-", suffix=".zip")
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in markdown_files:
                    archive.write(path, path.relative_to(source_dir).as_posix())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        archives += 1
        files += len(markdown_files)
        print(f"{target}: {len(markdown_files)} 份 Markdown")
    if not archives:
        raise ValueError(f"{source_dir}: 没有找到年份目录下的 Markdown")
    print(f"归档完成：{archives} 个压缩包，{files} 份 Markdown；原文件保留。")


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=root)
    parser.add_argument("--data-dir", type=Path, default=root / "data")
    args = parser.parse_args()
    archive_markdown(args.source_dir, args.data_dir)


if __name__ == "__main__":
    main()
