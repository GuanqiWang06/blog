#!/usr/bin/env python3
"""Create a new Markdown post.

Examples:
    python3 new.py "周末散步"
    python3 new.py "周末散步" weekend-walk
    python3 new.py "周末散步" weekend-walk --date 2026-11-20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content" / "posts"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def main() -> None:
    parser = argparse.ArgumentParser(description="新建一篇 Markdown 文章")
    parser.add_argument("title", help="文章标题")
    parser.add_argument("slug", nargs="?", help="英文短链接，例如 weekend-walk")
    parser.add_argument("--date", default=date.today().isoformat(), help="日期，默认今天")
    parser.add_argument("--description", default="", help="首页摘要，留空则自动取正文开头")
    args = parser.parse_args()

    try:
        post_date = date.fromisoformat(args.date)
    except ValueError:
        sys.exit("日期格式应为 YYYY-MM-DD")

    slug = args.slug.strip() if args.slug else "post"
    if not SLUG_RE.fullmatch(slug):
        sys.exit("slug 只能包含小写字母、数字和连字符，例如 weekend-walk")

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    path = CONTENT_DIR / f"{post_date.isoformat()}-{slug}.md"
    suffix = 2
    while path.exists():
        path = CONTENT_DIR / f"{post_date.isoformat()}-{slug}-{suffix}.md"
        suffix += 1

    front_matter = [
        "---",
        f"title: {json.dumps(args.title, ensure_ascii=False)}",
        f"date: {post_date.isoformat()}",
    ]
    if args.description.strip():
        front_matter.append(
            f"description: {json.dumps(args.description.strip(), ensure_ascii=False)}"
        )
    front_matter.append("---")
    front_matter.append("")

    body = """从这里开始写正文。

## 一个小标题

支持 Markdown：**加粗**、*斜体*、`行内代码`、[链接](https://example.com)、引用和列表。

> 一句值得单独留下的引用。

- 第一件事
- 第二件事
"""
    path.write_text("\n".join(front_matter) + "\n" + body, encoding="utf-8")

    print(f"已创建：{path.relative_to(ROOT)}")
    print("接下来：")
    print(f"  1. 编辑 {path.relative_to(ROOT)}")
    print("  2. 运行 python3 dev.py 预览，或 python3 build.py 生成静态页面")


if __name__ == "__main__":
    main()
