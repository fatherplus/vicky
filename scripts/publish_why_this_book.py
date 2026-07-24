#!/usr/bin/env python3
"""发布《为什么是这本书》设计说明文章 —— 走平台自己的 create_report（dogfooding）。
内容片段在同目录 why-this-book-content.html。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

content = (Path(__file__).resolve().parent / "why-this-book-content.html").read_text(encoding="utf-8")

result = server.create_report(
    title="为什么是这本书",
    slug="why-this-book",
    tag="META · 关于这本书本身",
    content=content,
    subtitle="ai-report 的配色、字体、版式、动效与组件——每一个决定背后的理由。这一页本身就是论据：它正用它所解释的那套风格说话。",
)
print(result)
