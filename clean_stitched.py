#!/usr/bin/env python3
"""从 translate_stitched_raw.png 生成干净的 translate_stitched_clean.png。

流程：
  1) 找「右侧大黑条」（整段没被任何帧覆盖的区域）→ 从它左边缘裁掉；
  2) 其余的块状黑区（面积足够大、不是细线）→ LaMa 修补；
  3) 去掉四周 1px 暗边；
  4) 横向拼接接缝：曝光台阶按列估计后用宽幅斜坡摊平，再纵向柔化残留细线。

用法: python clean_stitched.py 亚丝娜镜头1 亚丝娜镜头2
"""
import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

# 模型路径可移植：优先脚本同目录，再退回原来的工作区绝对路径（兼容旧环境）
DEFAULT_MODEL = Path(__file__).resolve().parent / "models" / "lama_fp32.onnx"


def resolve_model(model=None):
    p = Path(model) if model else DEFAULT_MODEL
    if p.exists():
        return p
    legacy = Path("/workspace/anime/models/lama_fp32.onnx")
    if legacy.exists():
        return legacy
    raise FileNotFoundError(
        f"找不到 LaMa 模型：{p}（用 --model 指定，或把 lama_fp32.onnx 放到 models/）")
# 「没被任何帧覆盖」的区域是纯黑 (0,0,0)；画面本身的暗部（暗蓝/暗红）不是纯黑，
# 用 max(B,G,R) < 6 才能把两者分开，否则会把暗背景当成缺口去补（会补成一片白）。
UNCOVERED_MAX = 6


# ---------------------------------------------------------------- 接缝修复
def find_hseams(im, thr=5.0, gap=25, max_n=6):
    """按整行均值找横向台阶；返回台阶所在行（台阶在该行与下一行之间）。"""
    f = im.astype(np.float32)
    H = f.shape[0]
    prof = f.mean(axis=(1, 2))
    d = np.abs(np.diff(prof))
    cand = []
    for y in np.where(d > thr)[0]:
        y = int(y)
        if y < 12 or y > H - 20:            # 贴边（内容突变）或没有衰减空间
            continue
        if cand and y - cand[-1][0] <= gap:
            if d[y] > cand[-1][1]:
                cand[-1] = (y, float(d[y]))
            continue
        cand.append((y, float(d[y])))
    cand.sort(key=lambda c: -c[1])
    return sorted(y for y, _ in cand[:max_n])


def region_step(f, y, band=6):
    """接缝上下各取 band 行求逐列色差，再沿 x 强平滑 → 平滑的二维补偿场。"""
    H = f.shape[0]
    up = f[max(0, y - band - 3):y].mean(axis=0)
    dn = f[y + 1:min(H, y + 1 + band)].mean(axis=0)
    S = np.clip((dn - up).astype(np.float32), -30, 30)
    return cv2.GaussianBlur(S[None], (101, 1), sigmaX=40, sigmaY=0)[0]


def soften_seam(out, y, half=5, sigma=1.8):
    """沿 y 局部高斯柔化，抹掉接缝残留的 1px 亮/暗线（横向完全不糊）。"""
    H = out.shape[0]
    pad = 6
    a, b = max(0, y - half), min(H - 1, y + half)
    s, e = max(0, a - pad), min(H, b + 1 + pad)
    if e - s < 5:
        return
    src = out[s:e].astype(np.float32)
    blur = cv2.GaussianBlur(src, (1, 9), sigmaX=0, sigmaY=sigma)
    win = np.hanning(11).astype(np.float32)
    win /= win.max()
    for i in range(a, b + 1):
        w = float(win[np.clip(int(round((i - a) / max(1, b - a) * 10)), 0, 10)])
        out[i] = src[i - s] * (1 - w) + blur[i - s] * w


def seam_fix(im, thr=5.0, tmin=120, tmax=700, verbose=True):
    out = im.astype(np.float32)
    H = out.shape[0]
    for y in find_hseams(im, thr):
        y0 = y + 1
        T = max(1, min(int(np.clip(H - y0, tmin, tmax)), H - y0))
        t = (np.arange(y0, H, dtype=np.float32) - y0) / T
        w = np.clip(1.0 - t, 0.0, 1.0) ** 2          # 接缝处 1 → T 行后 0
        out[y0:] -= region_step(out, y)[None] * w[:, None, None]
        soften_seam(out, y)
        if verbose:
            print(f'  接缝 y={y} 斜坡 {T}px')
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- LaMa
def lama_inpaint(img, mask, sess, size=512, stride=256):
    H, W = img.shape[:2]
    res = img.copy()
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return img
    y0g, y1g = int(ys.min()), int(ys.max()) + 1
    x0g, x1g = int(xs.min()), int(xs.max()) + 1
    for y in range(max(0, y0g - size // 2), y1g, stride):
        for x in range(max(0, x0g - size // 2), x1g, stride):
            y1, x1 = min(H, y + size), min(W, x + size)
            y0c, x0c = max(0, y1 - size), max(0, x1 - size)
            subm = mask[y0c:y1, x0c:x1]
            if (subm > 0).sum() < 20:
                continue
            sub = img[y0c:y1, x0c:x1]
            h, w = sub.shape[:2]
            rgb = cv2.cvtColor(sub, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            small = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
            m = (cv2.resize(subm, (size, size), interpolation=cv2.INTER_NEAREST) > 0).astype(np.float32)
            out = sess.run(None, {"image": small.transpose(2, 0, 1)[None],
                                  "mask": m[None, None]})[0][0].transpose(1, 2, 0)
            # 该 LaMa 导出模型直接输出 0~255；若拿到的是 0~1 再放大
            if out.max() <= 1.5:
                out = out * 255.0
            out = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
            reg = res[y0c:y1, x0c:x1]
            mm = subm > 0
            reg[mm] = out[mm]
            res[y0c:y1, x0c:x1] = reg
    return res


# ---------------------------------------------------------------- 清理主体
def black_components(im, min_area=2000):
    black = (im.max(axis=2) < UNCOVERED_MAX).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(black, 8)
    comps = []
    for i in range(1, n):
        a = int(st[i, cv2.CC_STAT_AREA])
        x, y = int(st[i, 0]), int(st[i, 1])
        w, h = int(st[i, 2]), int(st[i, 3])
        if a >= min_area and min(w, h) >= 16:
            comps.append({"id": i, "area": a, "x": x, "y": y, "w": w, "h": h})
    return lab, comps


def trim_dark_edges(img, thresh=25, ratio=0.35, max_px=8):
    def dark_frac(line):
        px = line if line.ndim == 1 else line.mean(axis=1)
        return float((px < thresh).mean())

    for _ in range(max_px):
        if img.shape[0] <= 4 or img.shape[1] <= 4:
            break
        hit = [k for k, v in {
            "top": dark_frac(img[0]), "bottom": dark_frac(img[-1]),
            "left": dark_frac(img[:, 0]), "right": dark_frac(img[:, -1]),
        }.items() if v >= ratio]
        if not hit:
            break
        if "top" in hit:
            img = img[1:]
        if "bottom" in hit and img.shape[0] > 4:
            img = img[:-1]
        if "left" in hit and img.shape[1] > 4:
            img = img[:, 1:]
        if "right" in hit and img.shape[1] > 4:
            img = img[:, :-1]
    return img


def trim_edge_lines(img, max_px=4, rel=0.85, absdiff=8.0, mae_tol=7.0):
    """裁掉 warpAffine 留下的一两像素亮/暗边线。

    判据是「贴边那一行/列的均值与往里 3 行/列的均值差得太多」，
    而不是绝对暗度——这样既能去掉暗边也能去掉亮边，且最多只动 max_px 像素。
    """
    g = None
    for _ in range(max_px):
        H, W = img.shape[:2]
        if H < 8 or W < 8:
            break
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        bad = {
            "top": (g[0].mean(), g[3].mean(), np.abs(g[0] - g[1:3].mean(axis=0)).mean()),
            "bottom": (g[-1].mean(), g[-4].mean(), np.abs(g[-1] - g[-3:-1].mean(axis=0)).mean()),
            "left": (g[:, 0].mean(), g[:, 3].mean(), np.abs(g[:, 0] - g[:, 1:3].mean(axis=1)).mean()),
            "right": (g[:, -1].mean(), g[:, -4].mean(), np.abs(g[:, -1] - g[:, -3:-1].mean(axis=1)).mean()),
        }
        hit = [k for k, (m, mi, mae) in bad.items()
               if m < mi * rel or m > mi / rel or abs(m - mi) > absdiff or mae > mae_tol]
        if not hit:
            break
        if "top" in hit:
            img = img[1:]
        if "bottom" in hit and img.shape[0] > 8:
            img = img[:-1]
        if "left" in hit and img.shape[1] > 8:
            img = img[:, 1:]
        if "right" in hit and img.shape[1] > 8:
            img = img[:, :-1]
    return img


def clean(raw_path, out_path, model=None, seam=True):
    im = cv2.imread(raw_path)
    H, W = im.shape[:2]
    lab, comps = black_components(im)
    print(f'  原始 {W}x{H}，未覆盖黑区 {len(comps)} 个:',
          [(c["x"], c["y"], c["w"], c["h"]) for c in comps])

    # 1) 右侧「大竖条」未覆盖区 → 从它的左边缘裁掉
    strip = [c for c in comps if c["w"] > W * 0.05 and c["h"] > H * 0.25
             and c["x"] + c["w"] >= W - 6]
    cut_w = W
    if strip:
        cut_w = max(1, max(strip, key=lambda c: c["area"])["x"])
        print(f'  裁掉右侧未覆盖条到 x={cut_w}')

    # 2) 左侧贴边的细黑条（帧左边缘）→ 一并裁掉
    cut_x0 = 0
    left = [c for c in comps if c["x"] <= 3 and c["w"] <= 12 and c["h"] > H * 0.2]
    if left:
        cut_x0 = max(c["x"] + c["w"] for c in left)
        print(f'  裁掉左侧黑边 {cut_x0}px')

    base = im[:, cut_x0:cut_w]
    lab, comps = black_components(base)
    print(f'  裁后 {base.shape[1]}x{base.shape[0]}，待修补黑区 {len(comps)} 个:',
          [(c["x"], c["y"], c["w"], c["h"]) for c in comps])

    # 3) 剩余未覆盖块 → LaMa
    mask = np.zeros(base.shape[:2], np.uint8)
    for c in comps:
        mask[lab == c["id"]] = 255
    if mask.any():
        mask = cv2.dilate(mask, np.ones((9, 9), np.uint8))
        sess = ort.InferenceSession(str(resolve_model(model)), providers=["CPUExecutionProvider"])
        out = lama_inpaint(base, mask, sess)
        m = mask > 0
        pm = out[m].mean(axis=0)
        print(f'  修补 {int(m.sum())} px，修补区均值 BGR={np.round(pm, 1)}')
        if pm.min() > 235:
            print('  ! 修补结果疑似纯白，回退为邻域填充')
            out = cv2.inpaint(base, mask, 7, cv2.INPAINT_TELEA)
    else:
        out = base.copy()

    # 3) 去四周 1~2px 的暗边/亮边
    out = trim_edge_lines(trim_dark_edges(out))

    # 4) 横向接缝曝光补偿（安全网；拼接阶段已做逐帧光度对齐后通常只剩很小残差）
    if seam:
        out = seam_fix(out)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), out)
    print('  ->', out_path, out.shape)
    return out


def main():
    ap = argparse.ArgumentParser(description="清理拼接图的黑块与接缝")
    ap.add_argument('inputs', nargs='*', help='目录 或 translate_stitched_raw.png 路径（可多个）')
    ap.add_argument('--model', help='LaMa onnx 路径（默认脚本同目录 models/lama_fp32.onnx）')
    ap.add_argument('--out', help='输出目录（默认与各自 raw 同目录）')
    ap.add_argument('--no-seam', action='store_true', help='跳过接缝曝光补偿')
    a = ap.parse_args()
    here = Path(__file__).resolve().parent
    inputs = a.inputs or [str(here / '亚丝娜镜头1'), str(here / '亚丝娜镜头2')]
    for src in inputs:
        p = Path(src)
        raw = p / 'translate_stitched_raw.png' if p.is_dir() else p
        if not raw.exists():
            print(f'跳过（{raw} 不存在）')
            continue
        outdir = Path(a.out) if a.out else raw.parent
        out = outdir / f'{raw.stem.replace("_raw", "")}_clean.png'
        print('==', raw)
        clean(str(raw), str(out), model=a.model, seam=not a.no_seam)


if __name__ == "__main__":
    main()
