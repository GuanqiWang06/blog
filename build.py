#!/usr/bin/env python3
"""Build the static blog from Markdown sources.

Usage:
    python3 build.py

Sources live in content/posts/*.md. Generated files are posts/*.html and the
archive section of index.html. Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import ast
import html
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content" / "posts"
POSTS_DIR = ROOT / "posts"
INDEX_FILE = ROOT / "index.html"
POST_TEMPLATE = ROOT / "templates" / "post.html"

MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
BUILD_BLOCK_RE = re.compile(
    r"(<!-- BUILD:POSTS_START -->).*?(<!-- BUILD:POSTS_END -->)", re.S
)
CODE_FENCE_RE = re.compile(r"^```([^\n]*)\n(.*?)\n```\s*$", re.S | re.M)


@dataclass
class Post:
    source: Path
    slug: str
    date: date
    title: str
    description: str
    meta_description: str
    minutes: int
    body_markdown: str
    body_html: str


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("\ufeff")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError("缺少 front matter（文件开头的 --- 区块）")

    meta: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"无法解析 front matter 行：{raw_line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            meta[key] = ""
        elif value[0] in "\"'" and value[-1] == value[0]:
            try:
                meta[key] = str(ast.literal_eval(value))
            except (ValueError, SyntaxError):
                meta[key] = value[1:-1]
        else:
            meta[key] = value
    return meta, text[match.end():].strip()


def plain_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fallback_description(markdown: str, limit: int = 96) -> str:
    first = ""
    for block in markdown.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(("#", ">", "```", "-", "*", "+")):
            continue
        if re.match(r"^\d+\.\s+", block):
            continue
        first = plain_text(block)
        if first:
            break
    if len(first) > limit:
        first = first[:limit].rstrip("，。；、 ") + "…"
    return first


def estimate_minutes(markdown: str) -> int:
    text = plain_text(markdown)
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    return max(1, round((cjk + words) / 300))


def resolve_url(url: str) -> str:
    """Make content-relative asset/post links work from the posts/ directory."""
    if url.startswith(("assets/", "posts/")):
        return "../" + url
    return url


def inline_markdown(text: str) -> str:
    code_spans: list[str] = []

    def store_code(match: re.Match[str]) -> str:
        code_spans.append(match.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", store_code, text)

    def image(match: re.Match[str]) -> str:
        alt, url, title = match.group(1), match.group(2), match.group(3)
        title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
        return (
            f'<img src="{html.escape(resolve_url(url), quote=True)}" '
            f'alt="{html.escape(alt, quote=True)}"{title_attr}>'
        )

    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)", image, text
    )

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        return (
            f'<a href="{html.escape(resolve_url(url), quote=True)}">'
            f"{inline_markdown(label)}</a>"
        )

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)

    for index, code in enumerate(code_spans):
        text = text.replace(
            f"\x00CODE{index}\x00", f"<code>{html.escape(code)}</code>"
        )
    return text


def is_block_start(line: str) -> bool:
    stripped = line.lstrip()
    return bool(
        stripped.startswith((">", "#", "```", "<"))
        or re.match(r"^\s*[-*+]\s+", line)
        or re.match(r"^\s*\d+\.\s+", line)
        or re.match(r"^\s*(?:---|\*\*\*|___)\s*$", line)
    )


def markdown_to_html(markdown: str) -> str:
    code_blocks: list[str] = []

    def store_block(match: re.Match[str]) -> str:
        language = match.group(1).strip()
        code = match.group(2)
        class_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
        code_blocks.append(f"<pre><code{class_attr}>{html.escape(code)}</code></pre>")
        return f"\x00BLOCK{len(code_blocks) - 1}\x00"

    markdown = CODE_FENCE_RE.sub(store_block, markdown)
    lines = markdown.splitlines()
    output: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        block_match = re.fullmatch(r"\x00BLOCK(\d+)\x00", line.strip())
        if block_match:
            output.append(code_blocks[int(block_match.group(1))])
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline_markdown(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        if re.match(r"^\s*(?:---|\*\*\*|___)\s*$", line):
            output.append("<hr>")
            i += 1
            continue

        if line.lstrip().startswith(">"):
            quoted: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                value = lines[i].lstrip()[1:]
                if value.startswith(" "):
                    value = value[1:]
                quoted.append(value.rstrip())
                i += 1
            inner = "<br>\n".join(inline_markdown(value) for value in quoted if value)
            output.append(f"<blockquote>\n<p>{inner}</p>\n</blockquote>")
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i], count=1))
                i += 1
            body = "\n".join(f"  <li>{inline_markdown(item)}</li>" for item in items)
            output.append(f"<ul>\n{body}\n</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i], count=1))
                i += 1
            body = "\n".join(f"  <li>{inline_markdown(item)}</li>" for item in items)
            output.append(f"<ol>\n{body}\n</ol>")
            continue

        if line.lstrip().startswith("<"):
            raw: list[str] = [line]
            i += 1
            while i < len(lines) and lines[i].strip():
                raw.append(lines[i])
                i += 1
            output.append("\n".join(raw))
            continue

        paragraph: list[str] = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not is_block_start(lines[i]):
            paragraph.append(lines[i])
            i += 1

        parts: list[str] = []
        for index, value in enumerate(paragraph):
            hard_break = value.endswith("  ")
            parts.append(value.rstrip())
            if index < len(paragraph) - 1:
                parts.append("<br>" if hard_break else "")
        output.append(f"<p>{inline_markdown(''.join(parts))}</p>")

    return "\n\n".join(output)


def load_posts() -> list[Post]:
    if not CONTENT_DIR.is_dir():
        raise SystemExit(f"找不到内容目录：{CONTENT_DIR}")

    posts: list[Post] = []
    slugs: dict[str, Path] = {}
    for path in sorted(CONTENT_DIR.glob("*.md")):
        match = FILENAME_RE.match(path.name)
        if not match:
            print(f"跳过 {path.name}：文件名应为 YYYY-MM-DD-slug.md", file=sys.stderr)
            continue

        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        title = meta.get("title", "").strip()
        if not title:
            raise SystemExit(f"{path.name} 缺少 title")

        try:
            filename_date = date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise SystemExit(f"{path.name} 的日期无效：{exc}") from exc

        front_date = meta.get("date", "").strip()
        if front_date:
            try:
                post_date = date.fromisoformat(front_date)
            except ValueError as exc:
                raise SystemExit(f"{path.name} 的 date 无效：{exc}") from exc
            if post_date != filename_date:
                raise SystemExit(
                    f"{path.name} 的日期与文件名不一致：{front_date} != {filename_date}"
                )
        else:
            post_date = filename_date

        slug = match.group(2)
        if slug in slugs:
            raise SystemExit(f"slug 重复：{slug}（{slugs[slug].name} 与 {path.name}）")
        slugs[slug] = path

        description = meta.get("description", "").strip() or fallback_description(body)
        meta_description = meta.get("meta_description", "").strip() or description

        try:
            minutes = int(meta.get("minutes", "") or estimate_minutes(body))
        except ValueError as exc:
            raise SystemExit(f"{path.name} 的 minutes 必须是整数") from exc
        minutes = max(1, minutes)

        posts.append(
            Post(
                source=path,
                slug=slug,
                date=post_date,
                title=title,
                description=description,
                meta_description=meta_description,
                minutes=minutes,
                body_markdown=body,
                body_html=markdown_to_html(body),
            )
        )

    posts.sort(key=lambda post: (post.date, post.slug), reverse=True)
    return posts


def render_post(post: Post, template: str) -> str:
    values = {
        "TITLE": html.escape(post.title),
        "DESCRIPTION": html.escape(post.description),
        "META_DESCRIPTION": html.escape(post.meta_description),
        "DATE_ISO": post.date.isoformat(),
        "DATE_CN": f"{post.date.year} 年 {post.date.month} 月 {post.date.day} 日",
        "MINUTES": str(post.minutes),
        "BODY": post.body_html,
        "YEAR": str(post.date.year),
    }
    output = template
    for key, value in values.items():
        output = output.replace("{{" + key + "}}", value)
    return output


def render_archive(posts: list[Post]) -> str:
    by_year: dict[int, list[Post]] = {}
    for post in posts:
        by_year.setdefault(post.date.year, []).append(post)

    lines: list[str] = []
    for year in sorted(by_year, reverse=True):
        lines.append('        <div class="year-group">')
        lines.append(f'          <h2 class="year-label">{year}</h2>')
        lines.append('          <ul class="post-list">')
        for post in by_year[year]:
            lines.extend(
                [
                    '            <li class="post" data-reveal>',
                    f'              <a href="posts/{post.slug}.html">',
                    f'                <h3 class="post-title">{html.escape(post.title)}',
                    '                  <svg class="post-arrow" viewBox="0 0 24 24" aria-hidden="true">',
                    '                    <path d="M5 12h14m-6-6 6 6-6 6"></path>',
                    "                  </svg>",
                    "                </h3>",
                    f'                <p class="post-excerpt">{html.escape(post.description)}</p>',
                    '                <p class="post-meta">',
                    f'                  <time datetime="{post.date.isoformat()}">'
                    f'{MONTHS[post.date.month - 1]} {post.date.day:02d}, {post.date.year}</time>',
                    '                  <span class="meta-dot" aria-hidden="true"></span>',
                    f"                  <span>阅读 {post.minutes} 分钟</span>",
                    "                </p>",
                    "              </a>",
                    "            </li>",
                ]
            )
        lines.append("          </ul>")
        lines.append("        </div>")
    return "\n".join(lines)


def build(verbose: bool = True) -> None:
    posts = load_posts()
    template = POST_TEMPLATE.read_text(encoding="utf-8")
    if not POSTS_DIR.is_dir():
        raise SystemExit(f"找不到输出目录：{POSTS_DIR}")

    generated = {f"{post.slug}.html" for post in posts}
    for post in posts:
        output = POSTS_DIR / f"{post.slug}.html"
        output.write_text(render_post(post, template), encoding="utf-8")

    for stale in POSTS_DIR.glob("*.html"):
        if stale.name not in generated:
            stale.unlink()
            if verbose:
                print(f"已删除过期页面：{stale.name}")

    index = INDEX_FILE.read_text(encoding="utf-8")
    if not BUILD_BLOCK_RE.search(index):
        raise SystemExit(
            "index.html 缺少构建标记：<!-- BUILD:POSTS_START --> / <!-- BUILD:POSTS_END -->"
        )
    archive = render_archive(posts)

    def replace_archive(match: re.Match[str]) -> str:
        if archive:
            return f"{match.group(1)}\n{archive}\n        {match.group(2)}"
        return f"{match.group(1)}\n        {match.group(2)}"

    index = BUILD_BLOCK_RE.sub(replace_archive, index, count=1)
    INDEX_FILE.write_text(index, encoding="utf-8")

    if verbose:
        if posts:
            print(f"已生成 {len(posts)} 篇文章：")
            for post in posts:
                print(f"  {post.date.isoformat()}  {post.slug}.html  {post.title}")
        else:
            print("content/posts 里还没有文章，首页归档已清空。")
        print(f"已更新 {INDEX_FILE.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 content/posts/*.md 生成静态博客")
    parser.add_argument("-q", "--quiet", action="store_true", help="不输出文章列表")
    args = parser.parse_args()
    build(verbose=not args.quiet)


if __name__ == "__main__":
    main()
