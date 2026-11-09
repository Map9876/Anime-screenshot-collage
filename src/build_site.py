#!/usr/bin/env python3
"""把 CodeBuddy 对话导出（JSON）生成静态网站。

产物：
  index.html              对话网页版（我说的 + AI 说的）
  devlog.html / devlog.md 「用户怎么开发的?」开发日志（只含用户原话）
  data/conversation.json  精简后的结构化对话
  data/user_messages.json 仅用户发言

用法：python3 src/build_site.py [对话导出.json]
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "conversation-export-20261104.json"
LATEST = ROOT / "data" / "latest_user_message.txt"
CST = timezone(timedelta(hours=8))

SECRETS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def redact(s: str) -> str:
    for p in SECRETS:
        s = p.sub("[已脱敏]", s)
    return s


def loads(s):
    try:
        return json.loads(s) if isinstance(s, str) else (s or {})
    except (ValueError, TypeError):
        return {}


def parse_time(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(CST)
    except Exception:
        return None


# ---------------------------------------------------------------- 提取对话
def load_turns():
    doc = json.loads(RAW.read_text(encoding="utf-8"))
    convs = doc["data"]["conversations"]
    turns = []
    for conv in convs:
        for req in conv.get("requests", []):
            ms = req.get("messages", [])
            ums = [m for m in ms if m.get("role") == "user"]
            if not ums:
                continue
            um = ums[0]
            blocks = loads(um.get("message")).get("content", [])
            text = "".join(b.get("text", "") for b in blocks
                           if isinstance(b, dict) and b.get("type") == "text")
            q = re.search(r"<user_query>(.*?)</user_query>", text, re.S)
            if q:
                user_text, kind = q.group(1).strip(), "user"
            else:
                # 上下文压缩产生的「Summary:」不是用户说的话，单独标记
                body = re.sub(r"<user_info>.*?</user_info>", "", text, flags=re.S)
                body = re.sub(r"<additional_data>.*?</additional_data>", "", body, flags=re.S)
                user_text, kind = body.strip(), "context"

            atexts, tools = [], []
            for m in ms:
                if m.get("role") != "assistant":
                    continue
                for b in loads(m.get("message")).get("content", []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and (b.get("text") or "").strip():
                        atexts.append(b["text"].strip())
                    elif b.get("type") == "tool-call":
                        tools.append(b.get("toolName") or "tool")

            t = parse_time(um.get("createdAt") or "")
            extra = loads(um.get("extra"))
            turns.append({
                "id": f"u-{len(turns) + 1}",
                "n": len(turns) + 1,
                "ts": t.isoformat() if t else "",
                "date": t.strftime("%Y-%m-%d") if t else "未知日期",
                "time": t.strftime("%H:%M") if t else "",
                "kind": kind,
                "model": extra.get("modelName") or "",
                "user": redact(user_text),
                "assistant": redact("\n\n".join(atexts)),
                "tools": tools,
            })

    # 导出文件截止之后的最新一条用户消息（生成器把 token 等敏感串已脱敏）
    if LATEST.exists():
        txt = redact(LATEST.read_text(encoding="utf-8").strip())
        if txt:
            turns.append({
                "id": f"u-{len(turns) + 1}", "n": len(turns) + 1,
                "ts": "", "date": "2026-11-09", "time": "",
                "kind": "user", "model": "", "user": txt,
                "assistant": "", "tools": [], "note": "导出文件之后追加的本次请求",
            })
    return turns


# ---------------------------------------------------------------- 迷你 Markdown
def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def md2html(md: str, base: int = 2) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    bullet = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
    while i < len(lines):
        line = lines[i]
        st = line.strip()
        if st.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            continue
        if st.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|\-]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in st.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join("<th>" + inline(c) + "</th>" for c in head)
            tb = "".join("<tr>" + "".join("<td>" + inline(c) + "</td>" for c in r) + "</tr>" for r in rows)
            out.append(f"<div class='table-wrap'><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            lv = min(len(m.group(1)) + base, 6)
            out.append(f"<h{lv}>" + inline(m.group(2)) + f"</h{lv}>")
            i += 1
            continue
        if st in ("---", "***", "___"):
            out.append("<hr>")
            i += 1
            continue
        if st.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip("> ").rstrip())
                i += 1
            out.append("<blockquote>" + inline("\n".join(buf)).replace("\n", "<br>") + "</blockquote>")
            continue
        if bullet.match(line):
            ordered = bool(re.match(r"^\s*\d+[.)]\s+", line))
            items = []
            while i < len(lines) and bullet.match(lines[i]):
                items.append(bullet.sub("", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join("<li>" + inline(x) + "</li>" for x in items) + f"</{tag}>")
            continue
        if not st:
            i += 1
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not (
            lines[i].strip().startswith("```") or lines[i].strip().startswith("|")
            or re.match(r"^#{1,6}\s", lines[i].strip()) or bullet.match(lines[i])
            or lines[i].strip().startswith("> ") or lines[i].strip() in ("---", "***", "___")
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + "<br>".join(inline(x) for x in buf) + "</p>")
    return "\n".join(out)


# ---------------------------------------------------------------- 页面片段
def preview(s: str, n: int = 46) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] + ("…" if len(s) > n else "")


def tool_summary(tools):
    if not tools:
        return ""
    names, counts = [], {}
    for t in tools:
        counts[t] = counts.get(t, 0) + 1
        if t not in names:
            names.append(t)
    lis = "".join(f"<li><code>{html.escape(t)}</code> ×{counts[t]}</li>" for t in names)
    return (f"<details class='tools'><summary>本轮工具调用 · {len(tools)} 次（展开）</summary>"
            f"<ul>{lis}</ul></details>")


def render_messages(turns, devlog=False):
    out = []
    for t in turns:
        if t["kind"] == "context":
            if devlog:
                continue
            out.append(
                f"<article class='turn context' id='{t['id']}'>"
                "<div class='msg context-msg'><div class='meta'><span class='badge ctx'>系统</span>"
                f"<time>{t['date']} {t['time']}</time><span class='muted'>上下文压缩摘要（非用户发言，已折叠）</span></div>"
                f"<details><summary>展开摘要</summary><div class='body'>{md2html(t['user'])}</div></details></div></article>"
            )
            continue

        meta = (f"<span class='badge me'>我</span><time>{t['date']} {t['time']}</time>"
                f"<span class='muted'>#{t['n']}</span>")
        if t["model"]:
            meta += f"<span class='model'>{html.escape(t['model'])}</span>"
        out.append(
            f"<article class='turn' id='{t['id']}' data-idx='{t['n']}'>"
            f"<div class='msg me-msg'><div class='meta'>{meta}</div>"
            f"<div class='body'>{md2html(t['user'])}</div></div>"
        )
        if not devlog:
            if t["assistant"]:
                out.append(
                    f"<div class='msg ai-msg' id='a-{t['n']}'>"
                    "<div class='meta'><span class='badge ai'>AI</span><span class='muted'>回复</span></div>"
                    f"<div class='body'>{md2html(t['assistant'])}</div>{tool_summary(t['tools'])}</div>"
                )
            elif t.get("note"):
                out.append(f"<div class='msg ai-msg'><div class='meta'><span class='badge ai'>AI</span></div>"
                           f"<div class='body muted'>{html.escape(t['note'])}：本次回复即生成本站点并推送，见 README。</div></div>")
        out.append("</article>")
    return "\n".join(out)


def build_nav(turns):
    user_nav, all_nav = [], []
    real = [t for t in turns if t["kind"] == "user"]
    for t in real:
        user_nav.append({"id": t["id"], "date": t["date"], "time": t["time"],
                         "n": t["n"], "text": preview(t["user"]), "full": t["user"]})
        all_nav.append({"id": t["id"], "date": t["date"], "time": t["time"],
                        "n": t["n"], "text": preview(t["user"]), "full": t["user"], "who": "我"})
        if t["assistant"]:
            all_nav.append({"id": f"a-{t['n']}", "date": t["date"], "time": t["time"],
                            "n": t["n"], "text": preview(t["assistant"]), "full": t["assistant"], "who": "AI"})
    return user_nav, all_nav


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="index.html">Anime Screenshot Collage <span class="sub">/ 对话存档</span></a>
    <nav class="topnav">
      <a href="index.html" class="{{ACTIVE_INDEX}}">完整对话</a>
      <a href="devlog.html" class="{{ACTIVE_DEVLOG}}">用户怎么开发的?</a>
      <a href="report.html">技术报告</a>
      <a href="https://github.com/Map9876/Anime-screenshot-collage" target="_blank" rel="noopener">GitHub ↗</a>
    </nav>
  </div>
</header>

<main class="wrap">
  <section class="hero">
    <h1>{{TITLE}}</h1>
    <p>{{SUBTITLE}}</p>
    <div class="stats">{{STATS}}</div>
  </section>
  <div id="messages">{{MESSAGES}}</div>
  <footer class="foot">由 <code>src/build_site.py</code> 从对话导出文件生成 · 原始导出见 <code>data/</code></footer>
</main>

<button id="tocToggle" type="button" aria-label="打开我说的话导航">☰ <span>我说的话</span> <b id="tocCount">0</b></button>

<aside id="toc" aria-label="发言导航">
  <div class="toc-head">
    <div class="tabs">
      <button class="tab active" data-tab="user">只看我说</button>
      <button class="tab" data-tab="all">全部发言</button>
    </div>
    <input id="tocSearch" type="search" placeholder="搜索我说的话…" autocomplete="off">
    <div class="toc-actions">
      <button id="jumpPrev" type="button" title="上一条我的发言">↑ 上一条</button>
      <button id="jumpNext" type="button" title="下一条我的发言">↓ 下一条</button>
      <label class="only"><input type="checkbox" id="onlyMine"> 仅显示我的发言</label>
    </div>
  </div>
  <nav id="tocList"></nav>
  <div class="toc-foot">点击任意条目即可跳转（类似 GitHub 的 # / ## 目录菜单）</div>
</aside>

<script>window.NAV_USER = {{NAV_USER}}; window.NAV_ALL = {{NAV_ALL}};</script>
<script src="assets/app.js"></script>
</body>
</html>
"""


def script_json(obj):
    # 防住用户文本里出现 </script> 提前闭合脚本块
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def write_page(path, title, subtitle, stats, messages, user_nav, all_nav, devlog=False):
    h = (PAGE.replace("{{TITLE}}", html.escape(title))
             .replace("{{SUBTITLE}}", html.escape(subtitle))
             .replace("{{STATS}}", stats)
             .replace("{{MESSAGES}}", messages)
             .replace("{{NAV_USER}}", script_json(user_nav))
             .replace("{{NAV_ALL}}", script_json(all_nav))
             .replace("{{ACTIVE_INDEX}}", "" if devlog else "active")
             .replace("{{ACTIVE_DEVLOG}}", "active" if devlog else ""))
    path.write_text(h, encoding="utf-8")
    print("写出", path.relative_to(ROOT), f"{len(h)/1024:.0f} KB")


REPORT_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>拼接与黑块清理技术报告</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="topbar"><div class="wrap">
  <a class="brand" href="index.html">Anime Screenshot Collage <span class="sub">/ 技术报告</span></a>
  <nav class="topnav">
    <a href="index.html">完整对话</a>
    <a href="devlog.html">用户怎么开发的?</a>
    <a href="report.html" class="active">技术报告</a>
    <a href="https://github.com/Map9876/Anime-screenshot-collage" target="_blank" rel="noopener">GitHub ↗</a>
  </nav>
</div></header>
<main class="wrap">
  <section class="hero"><h1>拼接与黑块清理技术报告</h1>
    <p>从纯平移拼接到黑块清理、接缝曝光修复的完整算法与实测指标；Markdown 原文见 docs/拼接清理报告.md。</p></section>
  <div class="msg"><div class="body">{{BODY}}</div></div>
  <footer class="foot">由 <code>src/build_site.py</code> 从 <code>docs/拼接清理报告.md</code> 生成</footer>
</main>
</body>
</html>
"""


def build_report():
    src = ROOT / "docs" / "拼接清理报告.md"
    if not src.exists():
        return
    body = re.sub(r"^# .*\n", "", src.read_text(encoding="utf-8"), count=1)
    out = REPORT_PAGE.replace("{{BODY}}", md2html(body, base=0))
    (ROOT / "report.html").write_text(out, encoding="utf-8")
    print("写出 report.html", f"{len(out)/1024:.0f} KB")


def main():
    turns = load_turns()
    real = [t for t in turns if t["kind"] == "user"]
    ctx = len(turns) - len(real)
    (ROOT / "data" / "conversation.json").write_text(
        json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "data" / "user_messages.json").write_text(
        json.dumps(real, ensure_ascii=False, indent=2), encoding="utf-8")

    user_nav, all_nav = build_nav(turns)
    stats = (f"<span>共 <b>{len(turns)}</b> 轮</span><span>我的发言 <b>{len(real)}</b> 条</span>"
             f"<span>AI 文字回复 <b>{sum(1 for t in turns if t['assistant'])}</b> 条</span>"
             f"<span>系统上下文摘要 <b>{ctx}</b> 条（不计入发言）</span>")

    write_page(ROOT / "index.html", "完整对话 · 我说的 + AI 说的",
               "按时间顺序完整还原对话；右下角悬浮按钮展开「只看我说」目录，点击即跳转。",
               stats, render_messages(turns), user_nav, all_nav)

    write_page(ROOT / "devlog.html", "用户怎么开发的?",
               "开发日志：逐字提取对话中「我说的全部内容」，按时间排序，不含 AI 回复。",
               stats, render_messages(turns, devlog=True), user_nav, user_nav, devlog=True)

    lines = [
        "# 用户怎么开发的?",
        "",
        "> 开发日志：从对话导出中逐字提取**用户说过的全部内容**，按时间顺序排列。",
        "> 不含 AI 回复；系统自动注入的上下文压缩摘要（%d 条）与工具调用已排除。" % ctx,
        "> 生成方式：`python3 src/build_site.py`；网页版见 [devlog.html](devlog.html)。",
        "",
        "---",
        "",
    ]
    date = None
    for t in real:
        if t["date"] != date:
            date = t["date"]
            lines += [f"## {date}", ""]
        head = f"### #{t['n']}"
        if t["time"]:
            head += f" · {t['time']}"
        if t["model"]:
            head += f" · {t['model']}"
        lines += [head, "", t["user"], ""]
    (ROOT / "devlog.md").write_text("\n".join(lines), encoding="utf-8")
    build_report()
    print("写出 devlog.md / data/*.json")
    print(f"统计：{len(turns)} 轮，用户发言 {len(real)} 条，上下文摘要 {ctx} 条，导航条目 {len(user_nav)}")


if __name__ == "__main__":
    main()
