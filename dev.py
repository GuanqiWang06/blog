#!/usr/bin/env python3
"""Build the blog, serve it locally, and rebuild when content changes.

Usage:
    python3 dev.py
    python3 dev.py --port 8000 --no-open
"""

from __future__ import annotations

import argparse
import http.server
import sys
import threading
import time
import webbrowser
from pathlib import Path

import build

ROOT = Path(__file__).resolve().parent


def snapshot() -> tuple[int, ...]:
    # Only watch sources. index.html is written by the build and would
    # otherwise trigger an endless rebuild loop.
    paths = [ROOT / "templates", ROOT / "content"]
    mtimes: list[int] = []
    for path in paths:
        if path.is_file():
            mtimes.append(path.stat().st_mtime_ns)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    mtimes.append(child.stat().st_mtime_ns)
    return tuple(mtimes)


def watch() -> None:
    last = snapshot()
    while True:
        time.sleep(1)
        current = snapshot()
        if current == last:
            continue
        last = current
        try:
            print("\n检测到内容变化，重新构建…")
            build.build(verbose=False)
        except Exception as exc:  # keep the server alive while the user fixes it
            print(f"构建失败：{exc}")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="本地预览博客，并在保存文章后自动重建")
    parser.add_argument("--port", type=int, default=8000, help="起始端口，默认 8000")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    build.build(verbose=False)
    threading.Thread(target=watch, daemon=True).start()

    server = None
    port = args.port
    for candidate in range(args.port, args.port + 20):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"端口 {args.port}–{args.port + 19} 都被占用了")

    url = f"http://localhost:{port}/"
    print(f"本地预览：{url}")
    print("保存 content/posts 里的文章后会自动重建，按 Ctrl+C 停止。")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
