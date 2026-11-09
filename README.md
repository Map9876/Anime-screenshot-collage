# Anime Screenshot Collage · 动漫截图拼接

把同一个（近似平移）镜头的多张动漫截图，用 OpenCV 拼成一张完整长图；再自动清理黑块、修复拼接接缝。
同时把**整个开发过程的对话**做成 GitHub Pages 网页版存档。

> 几个月前以及去年让 AI 尝试写过都没成功，这次让 AI 重写，结果 `cv2.Stitcher` 就能实现。
> 后续又发现透视投影会拉宽人物，于是改为**纯平移拼接**（零形状扭曲）。

## 在线访问

| 页面 | 地址 |
|---|---|
| 完整对话（我说的 + AI 说的） | https://map9876.github.io/Anime-screenshot-collage/ |
| 「用户怎么开发的?」开发日志 | https://map9876.github.io/Anime-screenshot-collage/devlog.html |
| 同上的 Markdown 版 | [devlog.md](devlog.md) |

> 站点已上线，Pages 源为 **`gh-pages` 分支 / `/`**（推这个分支时 GitHub 自动开启）。
> 一键复现方法见下节；**不需要进 Settings 改 source、不需要配 GitHub Actions、不需要把 `main` 设为发布源**。
> 仓库里附带的 `.github/workflows/sync-gh-pages.yml` 只是可选的自动同步（已开箱即用，删掉也不影响站点）。

## 一键生成 GitHub Pages（零配置）

核心就一句话：**推一个 `gh-pages` 分支，GitHub 会自动创建并发布 Pages**。
这是唯一需要的操作，Settings 里什么都不用点，也不需要任何 workflow。

```bash
git remote add origin https://github.com/<用户名>/<仓库名>.git
git push -u origin main

# ↓ 这一行就是「一键」：自动开启 Pages，站点立刻出现在
#   https://<用户名>.github.io/<仓库名>/
git push origin main:refs/heads/gh-pages
```

之后改了 `index.html` / 重新生成了对话网页，再推一次就会更新站点：

```bash
git push origin main                       # 推代码
git push origin main:refs/heads/gh-pages   # 推站点（main 是 gh-pages 的祖先，普通快进，无需 --force）
```

为什么这样最省事：

| 常见做法 | 需要用户做的事 |
|---|---|
| `main` / `root` 作源 | 进 Settings → Pages 手动选 source（本仓库的细粒度 PAT 还因缺 `pages:write` 权限调不动 API） |
| GitHub Actions 部署 | 配 workflow、`pages: write` 权限、artifact 上传 |
| **推 `gh-pages` 分支** | **零配置**，推完即上线，且 `main` 可以保持纯粹 |

仓库里放 `.nojekyll` 是为了让 Pages 原样提供 `assets/`、`data/` 等文件（不被 Jekyll 吞掉）。
`.github/workflows/sync-gh-pages.yml` 只是把上面第二条 `git push` 自动化了，**属于可选便利，不是必要条件**。

### 右下角悬浮导航怎么用

- 点右下角 **☰ 我说的话** 展开目录，默认标签是 **「只看我说」**：只列出用户发言，按日期分组（类似 GitHub 的 `#` / `##` 标题菜单）。
- 点任意条目 **直接跳转** 到那条发言，并高亮闪烁。
- 顶部搜索框可全文搜索我说的话；`↑ 上一条` / `↓ 下一条` 在发言之间顺序跳。
- 勾选 **「仅显示我的发言」** 可把页面上所有 AI 回复隐藏。
- 切到 **「全部发言」** 标签可看到用户 + AI 两类条目的联合目录。

## 拼接效果

| 亚丝娜镜头1（6 帧竖摇 → 全身像） | 亚丝娜镜头2（3 帧 → 特写） |
|---|---|
| ![镜头1 清理后](results/亚丝娜镜头1_clean.png) | ![镜头2 清理后](results/亚丝娜镜头2_clean.png) |

- 镜头1：**1573×3652**，最大行亮度跳变 `11.4 → 4.9`
- 镜头2：**2131×1649**，最大行亮度跳变 `9.4 → 1.8`
- 两图纯黑残留均为 `0.00%`

技术细节见 [docs/拼接清理报告.md](docs/拼接清理报告.md)。

## 目录结构

```
├── index.html                     # 对话网页版（静态 HTML，无需后端）
├── devlog.html / devlog.md        # 「用户怎么开发的?」：逐字提取的用户发言
├── assets/style.css, app.js       # 样式 + 悬浮目录交互（纯原生 JS）
├── data/
│   ├── conversation-export-20261104.json  # 原始对话导出文件（42 MB，原样保留）
│   ├── conversation.json                  # 精简结构化对话（供二次开发）
│   ├── user_messages.json                 # 仅用户发言
│   └── latest_user_message.txt            # 导出文件之后追加的最新一条（已脱敏）
├── docs/拼接清理报告.md           # 拼接与清理的技术报告
├── results/                       # 两张最终清理图
├── src/                           # 三个核心脚本（从 anime/ 摘出的可读副本）
│   ├── translate_stitch.py        # 纯平移拼接（SIFT + RANSAC + GraphCut 接缝）
│   ├── clean_stitched.py          # 黑块清理 + 接缝曝光修复 + LaMa 补洞
│   └── build_site.py              # 对话导出 → 静态网站生成器
├── anime/                         # ★ 完整原目录，原样整包推送（281 MB / 50 个文件）
│   ├── 亚丝娜镜头1/ 亚丝娜镜头2/  # 原始截图 + 每一版中间产物 + 最终 clean 图
│   ├── models/lama_fp32.onnx      # LaMa 修补模型（208 MB，走 Git LFS）
│   ├── README.md                  # 完整实验记录（Stitcher 畸变、APAP、裁剪鲁棒性、普适性测试…）
│   ├── translate_stitch.py / clean_stitched.py / lama_inpaint.py
│   ├── apap.py / diag.py / test_crops.py / translate_stitch_smooth.py
│   └── stitched_*.png / baseline_global.png / compare.png / synth_*.png …
├── .gitattributes                 # *.onnx filter=lfs（GitHub 单文件硬上限 100 MB）
└── .nojekyll                      # 让 Pages 原样提供 assets/ 与 data/
```

> `anime/` 是工作区 `/workspace/anime` 的**逐文件副本**，`src/` 只是三个主脚本的便捷副本，便于不翻目录就能看。
> 脚本保留了工作区原貌（`MODEL` 与 `root` 仍是 `/workspace/anime/...` 绝对路径），换机器运行前改成
> `anime/models/lama_fp32.onnx` 即可；克隆后需 `git lfs pull` 才会取回 208 MB 的模型实体
> （GitHub Pages 只用静态资源，不受影响）。

## 复现

```bash
# 1) 拼接（对存放截图的目录）
python3 src/translate_stitch.py "/path/to/亚丝娜镜头1"
# → translate_stitched.png / translate_stitched_raw.png / seam_mask.png

# 2) 清理黑块与接缝（需要 models/lama_fp32.onnx + onnxruntime）
python3 src/clean_stitched.py 亚丝娜镜头1 亚丝娜镜头2
# → translate_stitched_clean.png

# 3) 重新生成对话网站
python3 src/build_site.py [新的对话导出.json]
# → index.html / devlog.html / devlog.md / data/*.json
```

依赖：`opencv-python`、`numpy`、`onnxruntime`。网站本身是纯静态 HTML，无任何构建步骤、无外部 CDN。

## 数据来源与说明

- 对话网页版由 `data/conversation-export-20261104.json` 生成，即工作区里
  `/workspace/E-utilities API 可搜索 PubMed 文献_20261104160639.json` 的**原样副本**（仅改了个便于 URL 引用的文件名），包含 **101 轮**：
  **93 条用户发言**、AI 的文字回复、以及 **8 条系统自动注入的上下文压缩摘要**。
- 那 8 条摘要**不是用户说的话**，不进入「只看我说」目录和开发日志；在完整对话页里以可折叠灰条保留，保证对话不缺环。
- 工具调用与工具返回（共约 1200 次）不逐条铺开，只在每轮下方折叠列出调用的工具名；原始导出文件里完整保留。AI 的**内部推理（reasoning）也不算「说的话」**，因此不展示，页面只保留 AI 的实际文字回复。
- 最新一条用户请求发生在导出文件之后，由 `data/latest_user_message.txt` 追加；**其中的 GitHub Token 已脱敏**。
- 生成器还会对 `github_pat_` / `ghp_` / `sk-` / `AKIA` 等疑似凭据做统一脱敏。
- 原始导出文件原样公开在此仓库，请知悉它是公开可读的；若其中有不想公开的内容，删除
  `data/conversation-export-20261104.json` 后重跑 `src/build_site.py` 即可（网页版只依赖精简后的 `conversation.json`）。
