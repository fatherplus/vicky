#!/usr/bin/env python3
"""arch-flow 原型多页再生成：~/code/pi/dashboard/data/architecture.json →
public/prototype/arch-flow/（index.html 总览 + node-*.html 模块详情页）。
配色功能三色（蓝=计算流转 / 朱砂=判断器 / 灰=存储入口），边三型。
用法：python3 scripts/prototype_archflow.py"""
import json
import re
import sys
from pathlib import Path

SRC = Path.home() / "code/pi/dashboard/data/architecture.json"
OUT = Path(__file__).resolve().parents[1] / "public/prototype/arch-flow"
PAGE = OUT / "index.html"

EDGE_MAP = {"main": "main", "control": "main", "memory": "async", "async": "async", "warn": "warn"}
EDGE_TYPES = {
    "main": {"color": "#0C4A6E", "name": "请求 / 数据 / 控制"},
    "async": {"color": "#6E7278", "dash": "5,4", "name": "异步 / 记忆 / 持久化"},
    "warn": {"color": "#A63A2E", "dash": "5,4", "name": "安全拦截"},
}
STORE_NODES = {"mem", "persist"}
ENTRY_NODES = {"user"}

# 17 模块的输入/输出 example（原型演示数据，正式提交时由 AI 按契约填写）
EX = {
    "cc-safety-net": ('{ "command": "git clean -fdx" }',
                      '{ "verdict": "deny", "reason": "破坏性 git 命令：clean -fdx 会删除全部未跟踪文件",\n  "manualAdvice": "确认未跟踪清单后在终端手动执行" }'),
    "pi-web-access": ('web_search({ queries: ["Vue Flow vs React Flow 选型"] })',
                      '综合答案 + 3 条带来源引用'),
    "pi-agent-browser-native": ('agent_browser({ args: ["open", "http://localhost:9091"] })',
                                '{ title: "pi 工作环境…", url, snapshot: "@e1…@e14" }'),
    "pi-hashline-edit-pro": ('read → "E8b│ d.style.setProperty(--c, …)"',
                             'replace({ hash_range_inclusive: ["E8b","E8b"],\n  content_lines: ["…KIND_COLOR…"] })'),
    "pi-ast-grep": ('pattern: "console.log($A)"  language: ts',
                    '12 处命中 · 5 个文件（结构化匹配，非文本 grep）'),
    "@narumitw/pi-lsp": ('lsp_diagnostics({ paths: ["src/main.ts"] })',
                         '2 errors · 1 warning（TS2345: 类型不可赋值…）'),
    "@heyhuynhgiabuu/pi-diff": ('edit 前后两段文本',
                                '词级高亮 diff 块（Shiki 着色）'),
    "pi-codegraph-fix": ('codegraph_explore("COMPONENTS render 注入")',
                         '逐字源码 + 调用路径（跨项目 cwd 修复后命中）'),
    "pi-simplify": ('最近一次 commit 的 git diff',
                    '3 条建议：冗余分支 ×2 删除、重复判断合并 ×1'),
    "@dietrichgebert/ponytail": ('"给这个 API 加个缓存层"',
                                 '"@lru_cache(maxsize=1000)。跳过自定义 cache 类，\nlru_cache 不够用时再加。"'),
    "@quintinshaw/pi-dynamic-workflows": ('"并行从安全和性能两个角度审这个 diff"',
                                          'workflow 脚本 → parallel([secReview, perfReview])\n→ 汇总结论'),
    "@juicesharp/rpiv-todo": ('todo create "验证 arch-flow 渲染"',
                              '#3 pending → in_progress → completed'),
    "@juicesharp/rpiv-i18n": ('/languages → zh',
                              '命令描述与提示切中文'),
    "@narumitw/pi-statusline": ('当前 model + token 消耗 + git 分支',
                                'powerline 状态栏：model │ 12.4k tok │ main'),
    "superpowers-zh": ('任务：修复渲染 bug',
                       '自动注入 systematic-debugging skill'),
    "aimeter.ts": ('tier: "research"',
                   'model: "deepseek-v4-flash-official"\n（从 /v1/model/info 动态发现）'),
    "memory-weaver": ('会话轮次文本，含纠正信号："不对，颜色太多了"',
                      '偏好记忆：用户偏好收敛配色 → 下会话自动注入'),
}


def slug(mid: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", mid.lower()).strip("-")


def esc(s) -> str:
    import html as _h
    return _h.escape(str(s if s is not None else ""))


def io_block(k: str, tag: str, text, ex) -> str:
    return (f'<div class="af-io"><span class="af-io-k {k}">{tag}</span><div>'
            f"<code>{esc(text)}</code>"
            + (f"<details><summary>example</summary><pre>{esc(ex)}</pre></details>" if ex else "")
            + "</div></div>")


def module_sections(m: dict, ex) -> str:
    h = ""
    if m.get("purpose"):
        h += f'<section class="af-sec"><h4>定位</h4><p class="af-p">{esc(m["purpose"])}</p></section>'
    if m.get("input") or m.get("output"):
        h += ('<section class="af-sec"><h4>输入 / 输出</h4>'
              + (io_block("in", "IN", m.get("input"), ex[0] if ex else None) if m.get("input") else "")
              + (io_block("out", "OUT", m.get("output"), ex[1] if ex else None) if m.get("output") else "")
              + "</section>")
    if m.get("logic"):
        h += ('<section class="af-sec"><h4>工作逻辑</h4><ol>'
              + "".join(f"<li>{esc(x)}</li>" for x in m["logic"]) + "</ol></section>")
    if m.get("decisions"):
        h += ('<section class="af-sec"><h4>判断规则</h4><table class="af-dec">'
              + "".join(f"<tr><td>{esc(d['cond'])}</td><td class=\"af-dec-to\">→ {esc(d['to'])}</td></tr>"
                        for d in m["decisions"]) + "</table></section>")
    if m.get("provides"):
        prov = m["provides"]
        h += ('<section class="af-sec"><h4>提供能力</h4><p class="af-p">'
              + esc("；".join(prov) if isinstance(prov, list) else prov) + "</p></section>")
    return h


MOD_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 模块详情（arch-flow 原型）</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/book-style.css">
<link rel="stylesheet" href="../../assets/components/arch-flow/flow.css">
<style>
.mod-page{{max-width:860px;margin:0 auto;padding:64px 40px 90px}}
.mod-kicker{{font-family:var(--mono);font-size:12px;letter-spacing:.2em;color:var(--seal);margin-bottom:12px}}
.mod-title{{font-family:var(--mono);font-size:30px;font-weight:600;color:var(--ink);word-break:break-all;line-height:1.4}}
.mod-lead{{margin-top:14px;color:var(--sub);font-size:15px;line-height:1.9}}
.mod-body{{margin-top:10px}}
</style>
</head>
<body>
<div id="ribbon"></div>
<header class="topbar">
  <div class="bar-top">
    <a class="back" href="index.html">← 返回总览</a>
    <span class="bar-title">《{title}》</span>
    <span class="bar-seal">模</span>
  </div>
</header>
<main>
  <div class="mod-page">
    <div class="mod-kicker">MODULE · {cat}</div>
    <h1 class="mod-title">{title}</h1>
    <p class="mod-lead">{lead}</p>
    <div class="mod-body">
{sections}
    </div>
  </div>
</main>
</body>
</html>
"""


def main() -> int:
    src = json.loads(SRC.read_text())
    flow, mods, cats = src["flow"], src["modules"], src["categories"]
    catname = {c["id"]: c["name"] for c in cats}
    mod_by_id = {m["id"]: m for m in mods}

    nodes = []
    for n in flow["nodes"]:
        nd = {k: n[k] for k in ("id", "layer", "label", "sub", "kind", "module") if n.get(k) is not None}
        if n["id"] in STORE_NODES:
            nd["kind"] = "store"
        elif n["id"] in ENTRY_NODES:
            nd["kind"] = "entry"
        if n.get("module"):
            nd["href"] = f"node-{slug(n['module'])}.html"
        nodes.append(nd)

    edges = []
    for e in flow["edges"]:
        ed = {k: e[k] for k in ("from", "to", "label", "side", "dx") if e.get(k) is not None}
        ed["type"] = EDGE_MAP[e["type"]]
        edges.append(ed)

    modules = {}
    for m in mods:
        mm = {k: m[k] for k in ("cat", "source", "purpose", "provides", "input", "output", "logic", "decisions") if m.get(k)}
        mm["label"] = m["id"]
        modules[m["id"]] = mm

    contract = {
        "layers": flow["layers"],
        "nodes": nodes,
        "edges": edges,
        "edgeTypes": EDGE_TYPES,
        "categories": [{"id": c["id"], "name": c["name"]} for c in cats],
        "modules": modules,
    }
    flow_json = json.dumps(contract, ensure_ascii=False, indent=1)

    # ---- 总览页：JSON + 卡片（链接到模块页） ----
    cards = []
    for m in sorted(mods, key=lambda x: (x["cat"], x["id"])):
        cards.append(
            f'      <a class="mod-card" href="node-{slug(m["id"])}.html">\n'
            f'  <div class="mod-top"><span class="mod-cat">{esc(catname[m["cat"]])}</span>'
            f'<span class="mod-src">{esc(m.get("source", ""))}</span></div>\n'
            f'  <h3 class="mod-name">{esc(m["id"])}</h3>\n'
            f'  <p class="mod-purpose">{esc(m.get("purpose", ""))}</p>\n'
            f'</a>'
        )
    html = PAGE.read_text()
    html, n1 = re.subn(r'(<div class="arch-flow">\s*<script type="application/json">)[\s\S]*?(</script>)',
                       lambda m: m.group(1) + "\n" + flow_json + "\n      " + m.group(2), html, count=1)
    html, n2 = re.subn(r'(<div class="mod-grid">)\s*\n[\s\S]*?(\n    </div>)',
                       lambda m: m.group(1) + "\n" + "\n".join(cards) + m.group(2), html, count=1)
    if not (n1 and n2):
        print("总览页占位替换失败", n1, n2)
        return 1
    PAGE.write_text(html)

    # ---- 模块详情页 ----
    for m in mods:
        mid = m["id"]
        page = MOD_PAGE.format(
            title=esc(mid),
            cat=esc(catname[m["cat"]]),
            lead=esc(m.get("purpose", "")),
            sections=module_sections(m, EX.get(mid)),
        )
        (OUT / f"node-{slug(mid)}.html").write_text(page)

    print(f"OK: index {len(html)}B + {len(mods)} module pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
