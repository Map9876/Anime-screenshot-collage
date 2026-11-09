# 对话网页版存档（`gh-pages` 分支）

这个分支**只放静态网站**：完整对话（我说的 + AI 说的）、「用户怎么开发的?」开发日志，以及右下角的「只看我说」悬浮导航。
项目本体在 `main` 分支。

本项目由AI开发，全程聊天记录和提示词在 gh-pages分支的json文件，可直接导入codebuddy vscode插件使用进行二次开发，codebuddy cli或别的agent的话可能需要转换json一下。源仓库 https://cnb.cool/kfc50/sonypictures-poster

## 分支分工

| 分支 | 内容 | 用途 |
|---|---|---|
| `main` | `/workspace/anime` 的完整原目录（脚本、原始截图、全部中间产物、实验记录、`models/`），文件直接放在仓库根目录 | 项目源码 / 默认分支 |
| `gh-pages` | 本网站：`index.html`、`devlog.html`、`devlog.md`、`assets/`、`data/`、`docs/`、`results/`、`src/build_site.py`、`.nojekyll` | **GitHub Pages 发布源** |

| 页面 | 地址 |
|---|---|
| 完整对话 | https://map9876.github.io/Anime-screenshot-collage/ |
| 「用户怎么开发的?」 | https://map9876.github.io/Anime-screenshot-collage/devlog.html |
| 拼接与黑块清理技术报告 | https://map9876.github.io/Anime-screenshot-collage/report.html |

## 一键生成 GitHub Pages（零配置）

核心就一句：**推一个 `gh-pages` 分支，GitHub 会自动创建并发布 Pages**。
Settings 里什么都不用点，**不需要配 GitHub Actions，也不需要把 `main` 设为发布源**。

### 情景 A：站点和项目在同一个分支（最省事，一行搞定）

```bash
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main

# ↓ 这一行就是「一键」：自动开启 Pages
git push origin main:refs/heads/gh-pages
# → https://<用户名>.github.io/<仓库名>/
```

以后改了网页再推一次普通快进即可：`git push origin main:refs/heads/gh-pages`（`main` 是 `gh-pages` 的祖先，不需要 `--force`）。

### 情景 B：像本仓库这样两个分支内容不同

`main` 放项目、`gh-pages` 放网站，两边 **不是** 快进关系，直接推站点分支：

```bash
git checkout gh-pages
python3 src/build_site.py                 # 可选：从对话导出重新生成网页
git add -A && git commit -m "update site"
git push origin gh-pages                  # Pages 自动重新构建
```

> ⚠ 两分支内容不同时**不要**用 `git push origin main:gh-pages`，也不要加「自动把 main 同步到 gh-pages」的 workflow ——
> 那会把站点覆盖成项目文件。本分支已经删掉了那个 workflow。

### 为什么这个做法最省事

| 常见做法 | 需要用户做的事 |
|---|---|
| `main` / `root` 作发布源 | 进 Settings → Pages 手选 source（细粒度 PAT 还常因缺 `pages:write` 调不动 API） |
| GitHub Actions 部署 | 配 workflow、`pages: write` 权限、artifact 上传 |
| **推 `gh-pages` 分支** | **零配置**，推完即上线，`main` 可以保持纯粹 |

`.nojekyll` 用于让 Pages 原样提供 `assets/`、`data/` 等文件，不被 Jekyll 吞掉。

## 右下角悬浮导航

- 点右下角 **☰ 我说的话** 展开目录，默认标签「只看我说」：只列用户发言、按日期分组（类似 GitHub 的 `#` / `##` 标题菜单）。
- 点条目**直接跳转**并高亮闪烁；支持 `↑上一条 / ↓下一条` 顺序跳。
- 顶部可全文搜索；勾选「仅显示我的发言」隐藏全部 AI 回复；切「全部发言」看联合目录。

## 本分支目录

```
├── index.html / devlog.html / devlog.md   # 对话网页 / 开发日志（网页版 + Markdown 版）
├── report.html                           # 技术报告网页版（由 docs/*.md 渲染，站内直达）
├── assets/style.css, app.js              # 样式 + 悬浮目录交互（原生 JS，无 CDN）
├── data/
│   ├── conversation-export-20261104.json # 原始对话导出（42 MB，原样保留）
│   ├── conversation.json / user_messages.json
│   └── latest_user_message.txt           # 导出之后追加的最新一条（已脱敏）
├── docs/拼接清理报告.md                  # 拼接与黑块清理技术报告
├── results/                              # 两张最终清理图
├── src/build_site.py                     # 一键重生成整个静态站点
└── .nojekyll
```

重新生成：`python3 src/build_site.py [新的对话导出.json]` → 覆盖 `index.html`、`devlog.html`、`devlog.md`、`data/*.json`。
纯静态 HTML，无构建步骤、无后端、无外部依赖。

## 数据来源与说明

- 由 `data/conversation-export-20261104.json` 生成，即工作区里
  `/workspace/E-utilities API 可搜索 PubMed 文献_20261104160639.json` 的**原样副本**（只改了个便于 URL 引用的文件名），共 **101 轮**：
  **93 条用户发言**、AI 的文字回复、**8 条系统自动注入的上下文压缩摘要**。
- 那 8 条摘要不是用户说的话，不进入「只看我说」目录和开发日志；在完整对话页里折叠保留，保证对话不缺环。
- 约 1200 次工具调用/返回只在每轮下方折叠列出工具名；AI 的内部推理（reasoning）不算「说的话」，不展示。
- 最新一条用户请求由 `data/latest_user_message.txt` 追加，其中 GitHub Token 已脱敏；生成器还会对
  `github_pat_` / `ghp_` / `sk-` / `AKIA` 等疑似凭据统一脱敏。
- 原始导出文件在本分支公开可读；若有不想公开的内容，删掉它再重跑生成器即可（网页只依赖精简数据）。
