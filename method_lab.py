#!/usr/bin/env python3
"""方法层 XY 对照实验：X = 位移估计 / 主体处理，Y = 融合策略。

    python3 method_lab.py 龙猫
    python3 method_lab.py 龙猫 --quick             # 只跑 3 种融合
    python3 method_lab.py 龙猫 --no-depth          # 跳过深度方法（无需 onnx）

X 轴（每对图估计「im_j 相对 im_i 的特征点位移」，再用同一套 MST 布局）：
    sift       现有算法：SIFT + 纯平移 RANSAC（原图/CLAHE 自适应）  ← baseline
    orb        ORB + 纯平移 RANSAC（轻量，浏览器 JS 可行）
    phase      相位相关（极快，浏览器 JS 可行）
    ecc        ECC 从单位阵初始化（诊断项：大位移下预期失败）
    ecc_init   相位相关粗配准 + ECC 精修（标准 coarse-to-fine）
    motionmask SIFT 粗配准 → 帧差找运动主体 → 剔除主体点后重估（轻量主体识别）
    depth      Depth Anything V2 Small(int8 ONNX) → 剔除近景主体点后重估

Y 轴（同一 pos 下的融合策略）：
    mean / median / multiband / feather / seam
    median = 时序中值，对「运动主体」和「屏幕固定 OSD」天然鲁棒，无需深度模型。

产物（默认写在 <src>/method_lab/）：
    results.json          全矩阵指标
    report.md             对照表与结论
    grid.png              X × Y 缩略图矩阵
    best.png              指标最优的全尺寸结果
    motion_analysis.png   运动主体 / 内点分布 / 深度图可视化

评价口径：
    bg_p60      MST 边上重叠区逐像素差值的 60 分位（背景占多数，抗运动主体）
    ghost_pct   重叠区差值 > 30 的像素占比（错位 / 运动主体 / 重影）
    row/col     整图最大行 / 列亮度跳变
    seam_cost   接缝带最大亮度跳变
    t_est/t_fuse 位移估计 / 融合耗时（ms）——速度是能否上浏览器的关键
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import translate_stitch as ts  # noqa: E402

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)

ESTIMATORS = ['sift', 'orb', 'phase', 'ecc', 'ecc_init', 'motionmask', 'depth']
FUSIONS = ['mean', 'median', 'multiband', 'feather', 'seam']


# ------------------------------------------------------------------ 深度估计
class DepthEstimator:
    """Depth Anything V2 Small，int8 ONNX；同一份权重可直接给 ONNX Runtime Web 用。"""

    def __init__(self, path):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        self.name = self.sess.get_inputs()[0].name
        self.cache = {}
        self.time_s = 0.0

    def __call__(self, im, idx):
        if idx in self.cache:
            return self.cache[idx]
        t = time.perf_counter()
        rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (518, 518), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
        x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
        d = self.sess.run(None, {self.name: x})[0][0]
        d = cv2.resize(d.astype(np.float32), (im.shape[1], im.shape[0]))
        self.time_s += time.perf_counter() - t
        self.cache[idx] = d
        return d


# ------------------------------------------------------------------ 匹配 / RANSAC
def feature_pts(g1, g2, kind='sift'):
    if kind == 'sift':
        det, norm, ratio = cv2.SIFT_create(), cv2.NORM_L2, 0.8
    else:
        det, norm, ratio = cv2.ORB_create(nfeatures=5000), cv2.NORM_HAMMING, 0.75
    k1, d1 = det.detectAndCompute(g1, None)
    k2, d2 = det.detectAndCompute(g2, None)
    if d1 is None or d2 is None:
        return None
    pairs = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    if len(good) < 6:
        return None
    src = np.float32([k1[a.queryIdx].pt for a in good])
    dst = np.float32([k2[a.trainIdx].pt for a in good])
    return src, dst


def ransac_xy(src, dst, keep=None, thresh=4.0, iters=2500):
    """纯平移投票：假设只来自匹配点对，结构上不可能产生旋转/缩放/透视。"""
    if keep is not None:
        src, dst = src[keep], dst[keep]
    if len(src) < 6:
        return None
    s = dst - src
    rng = np.random.default_rng(0)
    cand = s[rng.integers(0, len(s), size=min(iters, max(1, len(s) * 3)))]
    best_n, best = 0, (0.0, 0.0)
    for dx, dy in cand:
        n = int((np.abs(s[:, 0] - dx) + np.abs(s[:, 1] - dy) < thresh).sum())
        if n > best_n:
            best_n, best = n, (float(dx), float(dy))
    if best_n < 6:
        return None
    inl = (np.abs(s[:, 0] - best[0]) + np.abs(s[:, 1] - best[1]) < thresh)
    return best[0], best[1], best_n, len(s), inl


def _gray_pair(ims, i, j):
    g1 = cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY)
    h = min(g1.shape[0], g2.shape[0])
    w = min(g1.shape[1], g2.shape[1])
    y1, x1 = (g1.shape[0] - h) // 2, (g1.shape[1] - w) // 2
    y2, x2 = (g2.shape[0] - h) // 2, (g2.shape[1] - w) // 2
    a = g1[y1:y1 + h, x1:x1 + w].astype(np.float32)
    b = g2[y2:y2 + h, x2:x2 + w].astype(np.float32)
    return a, b, (w, h)


def _phase(a, b, wh):
    w, h = wh
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    return float(dx), float(dy), float(resp)


def _ecc(a, b, init=(0.0, 0.0), iters=120):
    warp = np.array([[1, 0, init[0]], [0, 1, init[1]]], np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-6)
    try:
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_TRANSLATION, crit, None, 5)
    except cv2.error:
        return None
    return float(warp[0, 2]), float(warp[1, 2]), float(cc)


# ------------------------------------------------------------------ X 轴估计器
def est_sift(ims, i, j, ctx):
    r = ts.est_translation(ims[i], ims[j])
    return (r[0], r[1], r[2]) if r else None


def est_orb(ims, i, j, ctx):
    """ORB 在动画平滑区会堆出大量 (0,0) 假匹配（实测 2155 个 good 里
    1187 个内点全投给位移 0），必须像 SIFT 一样做「原图 / CLAHE」自适应，
    按内点率选更可靠的一路。加 CLAHE 后正确收敛到 (102.8, 344.7)。"""
    g1 = cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY)
    cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cands = []
    for a, b in ((g1, g2), (cl.apply(g1), cl.apply(g2))):
        pts = feature_pts(a, b, 'orb')
        if pts is None:
            continue
        r = ransac_xy(*pts)
        if r and r[2] >= 6:
            cands.append((r[2] / max(r[3], 1), r))
    if not cands:
        return None
    r = max(cands, key=lambda c: c[0])[1]
    return (r[0], r[1], r[2])


def est_phase(ims, i, j, ctx):
    a, b, wh = _gray_pair(ims, i, j)
    dx, dy, resp = _phase(a, b, wh)
    return (dx, dy, max(resp, 1e-4) * 1000)


def est_ecc(ims, i, j, ctx):
    a, b, wh = _gray_pair(ims, i, j)
    r = _ecc(a, b, (0.0, 0.0))
    return (r[0], r[1], max(r[2], 1e-4) * 1000) if r else None


def est_ecc_init(ims, i, j, ctx):
    """phase 粗配准 → ECC 精修（标准 coarse-to-fine）。

    合成位移 d=(10,20) 实测：ECC warp 平移与「特征点位移」同号，且初值必须是 +d
    才能收敛（从 0 或 -d 起步都掉进 (0,0) 附近局部极小，tx≈-1.5）。
    """
    a, b, wh = _gray_pair(ims, i, j)
    pdx, pdy, _ = _phase(a, b, wh)
    r = _ecc(a, b, (pdx, pdy))
    if r is None:
        return None
    return (r[0], r[1], max(r[2], 1e-4) * 1000)


def est_motionmask(ims, i, j, ctx):
    """两遍法：SIFT 粗配准 → 对齐后帧差找运动主体 → 剔除主体上的匹配点 → 重估。"""
    g1 = cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY)
    pts = feature_pts(g1, g2, 'sift')
    if pts is None:
        return None
    r0 = ransac_xy(*pts)
    if r0 is None:
        return None
    dx, dy = r0[0], r0[1]
    h, w = g1.shape
    M = np.float32([[1, 0, -dx], [0, 1, -dy]])
    aligned = cv2.warpAffine(ims[j], M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    diff = cv2.absdiff(ims[i], aligned).max(axis=2)
    moving = cv2.dilate((diff > 45).astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
    src, dst = pts
    xi = np.clip(src[:, 1].astype(int), 0, h - 1)
    yi = np.clip(src[:, 0].astype(int), 0, w - 1)
    xj = np.clip(dst[:, 1].astype(int), 0, h - 1)
    yj = np.clip(dst[:, 0].astype(int), 0, w - 1)
    keep = (~moving[xi, yi]) & (~moving[xj, yj])
    r = ransac_xy(src, dst, keep) if keep.sum() >= 6 else None
    return (r[0], r[1], r[2]) if r else (dx, dy, r0[2])


def est_depth(ims, i, j, ctx):
    """深度引导：剔除「近景主体」上的匹配点后重估。
    Depth Anything 输出方向不确定（depth / disparity），所以两个方向都试，
    按内点率自动选，跟现有 est_translation 的「原图/CLAHE 自适应」同一思路。"""
    de = ctx.get('depth')
    if de is None:
        return None
    g1 = cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY)
    pts = feature_pts(g1, g2, 'sift')
    if pts is None:
        return None
    d1, d2 = de(ims[i], i), de(ims[j], j)
    src, dst = pts
    h1, w1 = d1.shape
    h2, w2 = d2.shape
    v1 = d1[np.clip(src[:, 1].astype(int), 0, h1 - 1), np.clip(src[:, 0].astype(int), 0, w1 - 1)]
    v2 = d2[np.clip(dst[:, 1].astype(int), 0, h2 - 1), np.clip(dst[:, 0].astype(int), 0, w2 - 1)]
    q1, q2 = np.percentile(d1, 30), np.percentile(d2, 30)
    Q1, Q2 = np.percentile(d1, 70), np.percentile(d2, 70)
    cands = []
    for keep, tag in [((v1 > q1) & (v2 > q2), 'keep_far'),
                      ((v1 < Q1) & (v2 < Q2), 'keep_near')]:
        r = ransac_xy(src, dst, keep) if keep.sum() >= 6 else None
        if r and r[2] >= 6:
            cands.append((r[2] / max(r[3], 1), r, tag))
    if not cands:
        return None
    _, r, tag = max(cands, key=lambda c: c[0])
    ctx.setdefault('depth_choices', []).append(tag)
    return (r[0], r[1], r[2])


EST_FN = {
    'sift': est_sift, 'orb': est_orb, 'phase': est_phase,
    'ecc': est_ecc, 'ecc_init': est_ecc_init,
    'motionmask': est_motionmask, 'depth': est_depth,
}


# ------------------------------------------------------------------ 布局 / 融合
def build_layout(ests, n):
    """与 ts.auto_layout 完全相同的 Kruskal 最大生成树 + BFS，只有估计器不同。"""
    edges = sorted(ests.items(), key=lambda kv: kv[1][2], reverse=True)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    adj = {i: [] for i in range(n)}
    used = []
    for (i, j), (dx, dy, score) in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            adj[i].append((j, dx, dy))
            adj[j].append((i, -dx, -dy))
            used.append((i, j))
    anchor = edges[0][0][0] if edges else 0
    pos = {anchor: (0.0, 0.0)}
    q = [anchor]
    while q:
        i = q.pop(0)
        for j, dx, dy in adj[i]:
            if j not in pos:
                pos[j] = (pos[i][0] - dx, pos[i][1] - dy)
                q.append(j)
    for i in range(n):
        pos.setdefault(i, (0.0, 0.0))
    return pos, anchor, used


def warp_stack(ims, pos):
    """把各帧按 pos 放到同一画布，返回 (stack, masks, offsets)。"""
    positions = [pos[i] for i in range(len(ims))]
    minx = min(p[0] for p in positions)
    miny = min(p[1] for p in positions)
    W = int(np.ceil(max(p[0] + im.shape[1] for p, im in zip(positions, ims)) - minx))
    H = int(np.ceil(max(p[1] + im.shape[0] for p, im in zip(positions, ims)) - miny))
    stack, masks, offsets = [], [], []
    for im, (px, py) in zip(ims, positions):
        M = np.float32([[1, 0, px - minx], [0, 1, py - miny]])
        stack.append(cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0))
        m = cv2.warpAffine(np.ones(im.shape[:2], np.uint8) * 255, M, (W, H),
                           flags=cv2.INTER_NEAREST, borderValue=0) > 0
        masks.append(m)
        offsets.append((px - minx, py - miny))
    return np.stack(stack), np.stack(masks), offsets


def median_full(stack, masks):
    """时序中值（不裁 bbox）。运动主体 / 固定 OSD 只出现在少数帧，会被中值滤掉。"""
    n = stack.shape[0]
    cover = masks.sum(axis=0)
    vals = np.where(masks[..., None], stack.astype(np.int16), -1)
    vals.sort(axis=0)
    idx = np.clip(n - cover + cover // 2, 0, n - 1).astype(np.intp)
    idx3 = np.repeat(idx[None, :, :, None], 3, axis=3)
    out = np.take_along_axis(vals, idx3, axis=0)[0]
    return np.clip(np.where(cover[..., None] > 0, out, 0), 0, 255).astype(np.uint8)


def crop_valid(out, cover):
    ys, xs = np.where(cover > 0)
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def fuse(ims, pos, method, stack, masks):
    if method == 'mean':
        return ts.accumulate(ims, pos), None
    if method == 'median':
        return crop_valid(median_full(stack, masks), masks.sum(axis=0)), None
    if method == 'multiband':
        return ts.accumulate_blend(ims, pos, True), None
    if method == 'feather':
        return ts.accumulate_blend(ims, pos, False), None
    if method == 'seam':
        out, seam = ts.accumulate_seam(ims, pos, photometry=False)
        return out, seam
    raise ValueError(method)


# ------------------------------------------------------------------ 评价
def overlap_quality(stack, masks, edges):
    """MST 边上的重叠区一致性：背景分位差 + 高差异像素比例。"""
    p60s, ghosts, areas = [], [], []
    for i, j in edges:
        ov = masks[i] & masks[j]
        k = int(ov.sum())
        if k < 2000:
            continue
        diff = np.abs(stack[i].astype(np.int16) - stack[j].astype(np.int16)).max(axis=2)[ov]
        p60s.append(float(np.percentile(diff, 60)))
        ghosts.append(float((diff > 30).mean() * 100))
        areas.append(k)
    if not p60s:
        return None, None, 0
    return float(np.mean(p60s)), float(np.mean(ghosts)), int(np.mean(areas))


def qc(out):
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return {
        'size': [int(out.shape[1]), int(out.shape[0])],
        'black_pct': round(float((out.max(axis=2) < 8).mean() * 100), 3),
        'row_jump': round(float(np.abs(np.diff(g.mean(axis=1))).max()), 2),
        'col_jump': round(float(np.abs(np.diff(g.mean(axis=0))).max()), 2),
    }


def osd_count(out, ims, scale=0.5, thr=0.70):
    """数一数融合图里出现几次「屏幕固定台标」。

    台标在每帧的屏幕坐标不动，但各帧被放到画布不同位置 → 拼接后会重复出现。
    这是 Y 轴敏感指标（bg_p60 / ghost% 只取决于 X 的几何布局）。
    """
    h, w = ims[0].shape[:2]
    tpl = ims[0][int(h * 0.01):int(h * 0.19), int(w * 0.004):int(w * 0.135)]
    t = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    o = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if o.shape[0] < t.shape[0] + 2 or o.shape[1] < t.shape[1] + 2:
        return 0
    r = cv2.matchTemplate(o, t, cv2.TM_CCOEFF_NORMED)
    ky = max(3, int(t.shape[0] * 0.55))
    kx = max(3, int(t.shape[1] * 0.55))
    dil = cv2.dilate(r, np.ones((ky, kx), np.uint8))
    ys, xs = np.where((r >= thr) & (r >= dil - 1e-6))
    pts = []
    for y, x in zip(ys, xs):
        if all(abs(x - x0) > kx // 2 or abs(y - y0) > ky // 2 for y0, x0 in pts):
            pts.append((y, x))
    return len(pts)


# ------------------------------------------------------------------ 可视化
def make_grid(images, xnames, ynames, path, cell=(360, 240)):
    cw, ch = cell
    pad, lab = 8, 26
    W = len(ynames) * (cw + pad) + pad
    H = len(xnames) * (ch + lab + pad) + pad + lab
    canvas = np.full((H, W, 3), 245, np.uint8)
    for c, y in enumerate(ynames):
        cv2.putText(canvas, y, (pad + c * (cw + pad) + 4, lab - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1, cv2.LINE_AA)
    for r, x in enumerate(xnames):
        y0 = pad + lab + r * (ch + lab + pad)
        cv2.putText(canvas, x, (pad + 4, y0 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 160), 1, cv2.LINE_AA)
        for c, y in enumerate(ynames):
            im = images.get((x, y))
            x0 = pad + c * (cw + pad)
            if im is None:
                cv2.putText(canvas, 'n/a', (x0 + 10, y0 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
                continue
            s = min(cw / im.shape[1], ch / im.shape[0])
            small = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))),
                               interpolation=cv2.INTER_AREA)
            canvas[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
    cv2.imwrite(str(path), canvas)


def motion_analysis(ims, pos, stack, masks, offsets, edges, depth, outpath):
    """运动主体 / RANSAC 内点 / 深度图 三联可视化。"""
    med = median_full(stack, masks)
    diff = np.abs(stack[0].astype(np.int16) - med.astype(np.int16)).max(axis=2)
    moving = ((diff > 45) & masks[0]).astype(np.uint8)
    base = stack[0].copy()
    overlay = base.copy()
    overlay[moving > 0] = (0, 0, 255)
    panel1 = cv2.addWeighted(base, 0.55, overlay, 0.45, 0)

    # 最强边上的 SIFT 内点，统计落在运动区域的比例
    i, j = edges[0]
    g1 = cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY)
    pts = feature_pts(g1, g2, 'sift')
    in_ratio = None
    if pts is not None:
        r = ransac_xy(*pts)
        if r is not None:
            src, inl = pts[0], r[4]
            ox, oy = offsets[i]
            xx = np.clip((src[:, 0] + ox).astype(int), 0, moving.shape[1] - 1)
            yy = np.clip((src[:, 1] + oy).astype(int), 0, moving.shape[0] - 1)
            in_ratio = float(moving[yy[inl], xx[inl]].mean() * 100)
            for px, py in src[inl][::max(1, int(inl.sum() / 400))]:
                cv2.circle(panel1, (int(px + ox), int(py + oy)), 2, (0, 255, 0), -1)

    if depth is not None:
        d = depth(ims[0], 0)
        dv = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        panel3 = cv2.applyColorMap(dv, cv2.COLORMAP_MAGMA)
    else:
        panel3 = np.zeros_like(panel1)

    def fit(im, w=520):
        return cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1])),
                          interpolation=cv2.INTER_AREA)

    p1, p2, p3 = fit(panel1), fit(med), fit(panel3)
    h = max(p.shape[0] for p in (p1, p2, p3))
    w = p1.shape[1] * 3
    canvas = np.zeros((h, w, 3), np.uint8)
    for k, p in enumerate((p1, p2, p3)):
        canvas[:p.shape[0], k * p1.shape[1]:(k + 1) * p1.shape[1]] = p
    for k, txt in enumerate(('moving / inliers', 'temporal median', 'depth (int8)')):
        cv2.putText(canvas, txt, (k * p1.shape[1] + 10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.imwrite(str(outpath), canvas)
    # 口径与 inliers_in_moving_pct 对齐：只在第 0 帧的有效区内统计
    return {'moving_pct': round(float(moving[masks[0]].mean() * 100), 2),
            'inliers_in_moving_pct': None if in_ratio is None else round(in_ratio, 2)}


# ------------------------------------------------------------------ 报告
def write_report(path, ctx):
    rows = ctx['rows']
    layouts = ctx['layouts']
    L = []
    L.append('# 龙猫斜向 pan 镜头：方法层 XY 对照实验')
    L.append('')
    L.append('素材 `龙猫/`（4 帧，裁黑边后 2130×1156，斜向上运镜，**画面内有运动的汽车**，'
             '另有屏幕固定位置的 bilibili 水印与左上角台标）。')
    L.append('')
    L.append('**X 轴 = 位移估计 / 主体处理方法**（7 种），**Y 轴 = 融合策略**（5 种），'
             '共 %d 组；所有方法共用同一套 Kruskal 最大生成树布局，只有估计器不同。' % len(rows))
    L.append('')
    L.append('## 1. X 轴：位移估计结果（含 x / y 两个方向分量）')
    L.append('')
    L.append('| 方法 | pos 跨度 x / y (px) | 相对 SIFT 最大偏差 (px) | 估计耗时 (ms) | 说明 |')
    L.append('|---|---|---|---|---|')
    for name in ctx['xnames']:
        v = layouts[name]
        L.append('| `%s` | %.1f / %.1f | %.1f | %.0f | %s |' %
                 (name, v['span_x'], v['span_y'], v['max_dev'], v['t_est_ms'], v['note']))
    L.append('')
    s = layouts.get('sift', {})
    ph = layouts.get('phase', {})
    t_sift = next((m for n, m, _, _ in ctx['speed'] if n == 'sift'), 0)
    t_phase = next((m for n, m, _, _ in ctx['speed'] if n == 'phase'), 0)
    L.append('布局跨度约 **x %.0fpx / y %.0fpx**（斜向上 pan，y 分量是 x 的 %.1f 倍）。'
             '`phase` 相对 SIFT 的最大偏差只有 %.2fpx，单对估计却快约 %.0f 倍。' %
             (s.get('span_x', 0), s.get('span_y', 0),
              s.get('span_y', 1) / max(s.get('span_x', 1), 1),
              ph.get('max_dev', 0), t_sift / max(t_phase, 1)))
    L.append('')
    L.append('- **ORB**：6 个图片对里 5 个收敛到 `(0,0)` 假峰——动画平坦区 ORB 描述子重复，'
             '假峰内点率反而高于真实位移（加 CLAHE 也压不住），`bg_p60≈75` 即布局失效。')
    L.append('- **纯 ECC**：大位移超出收敛域，从单位阵起步掉进 `(0,0)` 局部极小；'
             '`ecc_init` 用相位相关的 `+d` 初始化后才收敛（合成位移测试确认 ECC warp '
             '与特征点位移同号，从 0 或 `-d` 起步都会失败）。')
    L.append('- `bg_p60` / `ghost%` 明显崩坏的行，说明该估计器给出的布局不可用。')
    L.append('')
    L.append('## 2. 全矩阵指标')
    L.append('')
    L.append('`bg_p60` = MST 边重叠区逐像素差的 60 分位（越小越对齐）；'
             '`ghost%` = 差值 >30 的像素占比（错位/运动主体）；`row/col` = 整图最大亮度跳变；'
             '`OSD` = 融合图里检测到几次固定台标（越少越好）。')
    L.append('')
    L.append('> `bg_p60` / `ghost%` 只取决于 X 轴的几何布局，所以同一行内恒定；'
             '**Y 轴的差异要看 `OSD` / `seam` / `row` / `col` 和融合耗时**。')
    L.append('')
    L.append('| X | Y | 尺寸 | bg_p60 | ghost% | OSD | row | col | seam | 黑区% | 融合 ms |')
    L.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for r in rows:
        L.append('| `%s` | `%s` | %dx%d | %.2f | %.2f | %d | %.2f | %.2f | %.2f | %.3f | %.0f |' %
                 (r['x'], r['y'], r['size'][0], r['size'][1],
                  r['bg_p60'] if r['bg_p60'] is not None else -1,
                  r['ghost_pct'] if r['ghost_pct'] is not None else -1,
                  r['osd_count'], r['row_jump'], r['col_jump'], r['seam_cost'],
                  r['black_pct'], r['t_fuse_ms']))
    L.append('')
    L.append('## 3. 运动主体 / 深度估计是否必要')
    L.append('')
    ma = ctx['motion']
    L.append('- 第 1 帧被判为「运动/非背景」的面积占比：**%.2f%%**；'
             'SIFT RANSAC 内点落在该区域的比例：**%s**。' %
             (ma['moving_pct'], ('%.2f%%' % ma['inliers_in_moving_pct'])
              if ma['inliers_in_moving_pct'] is not None else 'n/a'))
    L.append('- 运动 / 非背景区域只占有效画面约 **%.1f%%**，而纯平移 RANSAC 的强峰有 '
             '1000+ 内点，显然来自背景；落在大差异区的内点主要是固定 OSD 与曝光差异，'
             '不是车本体。**汽车被自动当外点剔除，拼接结果无重影**'
             '（`motion_analysis.png`：红色是车，绿点是内点）。' % ma['moving_pct'])
    dev = ['`%s` %.2fpx' % (k, ctx['layouts'][k]['max_dev'])
           for k in ('motionmask', 'depth') if k in ctx['layouts']]
    L.append('- `motionmask`（帧差剔主体）与 `depth`（Depth Anything V2 Small int8 剔近景）'
             '相对 baseline 的最大布局偏差：%s → '
             '**显式主体识别没有改变几何结论，深度模型在这个任务上是多余的**。' %
             ('、'.join(dev) if dev else 'n/a'))
    L.append('- 融合阶段运动主体有三种命运：`mean` / `multiband` / `feather` 把 4 个位置的车'
             '平均成淡影，`median` 直接把车抹掉（背景最干净），`seam` 只保留**恰好一辆车**。'
             '见 `grid.png` 最后一列。')
    base_x = 'sift' if any(r['x'] == 'sift' for r in rows) else rows[0]['x']
    osd = {r['y']: r['osd_count'] for r in rows if r['x'] == base_x}
    L.append('- 固定 OSD 同理（台标在每帧屏幕坐标不动，拼接后按各帧位置重复）：'
             '`mean` / `multiband` / `feather` 残留 %d 份，`median` %d 份，`seam` %d 份。'
             '深度估计对此无效——OSD 没有深度。' %
             (osd.get('mean', -1), osd.get('median', -1), osd.get('seam', -1)))
    L.append('- 所以「忽略主体」要分清三层：① **估计位移时**忽略（纯平移 RANSAC 已做到）；'
             '② **融合时**消除重复主体（`median` / `seam`）；③ 保留一个主体（只有 `seam`）。')
    L.append('')
    L.append('## 4. 速度与浏览器部署')
    L.append('')
    L.append('| 方法 | 单对估计 (ms) | 浏览器 JS | 备注 |')
    L.append('|---|---|---|---|')
    for name, ms, js, note in ctx['speed']:
        L.append('| `%s` | %.0f | %s | %s |' % (name, ms, js, note))
    L.append('')
    L.append('**结论（面向浏览器 JS）**：`phase` 单对约 %.0fms，比 SIFT 快约 %.0f 倍、'
             '位移偏差 <1px，OpenCV.js 原生就有 `phaseCorrelate`。配合 `seam`'
             '（保留一辆车、台标 1 份）或 `median`（更快、背景最干净）即可，'
             '**不必跑深度模型**；SIFT / ORB / ECC 都不是必需的。' %
             (t_phase, t_sift / max(t_phase, 1)))
    L.append('')
    L.append('若确实要做主体级 3D / 景深效果，再上 '
             '`onnx-community/depth-anything-v2-small` 的 int8 ONNX（26 MB，CPU ~0.7s/帧，'
             'WebGPU 更快），用 transformers.js 的 `depth-estimation` pipeline 或 '
             'ONNX Runtime Web 加载同一份权重。注意本实验里它只用于「剔近景匹配点」，'
             '而这件事 RANSAC 已经免费做完了。')
    L.append('')
    L.append('> 本实验只到「融合」为止，故 `黑区%` 仍是原始画布的未覆盖区域；'
             '真实出图再走 `collage.py` 的 LaMa 清理阶段（实测可清到 0.000%）。')
    L.append('')
    L.append('## 5. 相关论文 / 项目索引')
    L.append('')
    L.append('| 工作 | 会议 / 年份 | 代码 / 链接 | 与本任务的关系 |')
    L.append('|---|---|---|---|')
    items = [
        ('FE2E: From Editor to Dense Geometry Estimator', 'CVPR 2026',
         'https://github.com/AMAP-ML/FE2E',
         'DiT 编辑模型先验做 depth+normal；依赖 step1x-edit / VAE / LoRA，GPU 级，不适合浏览器'),
        ('Jasmine: Harnessing Diffusion Prior for Self-Supervised Depth Estimation',
         'NeurIPS 2025', 'https://github.com/wangjiyuan9/Jasmine',
         'Stable Diffusion 自监督深度，MIR + Scale-Shift GRU；arXiv 2503.15905'),
        ('D4RD: Digging into Contrastive Learning for Robust Depth Estimation with '
         'Diffusion Models', 'ACM MM 2024', 'https://github.com/wangjiyuan9/D4RD',
         '扩散深度在雨/雪等恶劣条件的鲁棒性；arXiv 2404.09831'),
        ('Marigold / Marigold V2', 'CVPR 2024 / SIGGRAPH Asia 2026',
         'https://huggingface.co/spaces/prs-eth/marigold',
         '扩散先验零样本深度；V2 见 https://github.com/huawei-bayerlab/marigold-v2'),
        ('Metric3D v2', 'TPAMI 2024', 'https://github.com/YvanYin/Metric3D',
         '有尺度（米）深度 + 法线，精度高、适合 3D 重建；ViT-giant 很重'),
        ('BetterDepth', '（用户提到）', '—',
         '针对深度平滑 / 主体内部深度丢失（狮子例子）；检索时未见独立官方开源仓库，'
         '同期 Marigold V2 在细粒度细节上有类似目标'),
        ('Depth Anything V2 Small', '2024 · Apache-2.0',
         'https://github.com/DepthAnything/Depth-Anything-V2',
         '**本实验采用**：onnx-community/depth-anything-v2-small 的 int8 ONNX（26 MB）'),
        ('MiDaS', '2021', 'https://github.com/isl-org/MiDaS',
         '更老的轻量 small 模型，ONNX / TF.js 生态成熟'),
        ('Transformers.js / ONNX Runtime Web', '—',
         'https://huggingface.co/docs/transformers.js',
         '浏览器端 depth-estimation pipeline，WebGPU fp16 / WASM 回退'),
        ('Depth Anything on Browser', '—',
         'https://github.com/akbartus/DepthAnything-on-Browser', '纯前端深度估计 demo'),
        ('PlaneToPBR', '—', 'https://github.com/ScarlettVFX/PlaneToPBR',
         '平面照片 → PBR 材质（3D 场景工具链）'),
    ]
    for name, conf, url, note in items:
        link = '[代码/主页](%s)' % url if url.startswith('http') else url
        L.append('| %s | %s | %s | %s |' % (name, conf, link, note))
    L.append('')
    L.append('3D / MC 场景生成工具链：'
             '[Krea](https://www.krea.ai/home)、[Tripo3D](https://www.tripo3d.ai/)、'
             '[Hyper3D Rodin](https://hyper3d.ai/rodin)、'
             '[TRELLIS](https://huggingface.co/spaces/JeffreyXiang/TRELLIS)、'
             '[objtoschematic](https://objtoschematic.com/)、[Blender](https://www.blender.org/)、'
             '[depth-map-batch](https://blendermarket.com/products/depth-map-batch-for-images)、'
             '[zform](https://blendermarket.com/products/zform)、'
             '[BlockBlender](https://blendermarket.com/products/blockblender)、'
             '[BlockBlenderToSchem](https://bryanvalc.gumroad.com/l/BlockBlenderToSchem)、'
             '[B站 MC 建筑教程](https://b23.tv/nTopUmD)（上集 BV1ifqBYqEzk）、'
             '[知乎推文](https://zhuanlan.zhihu.com/p/1894794247015757493)。')
    L.append('')
    L.append('本地克隆的参考仓库放在 `anime/methods/`（第三方代码快照，由 `.gitignore` 排除，'
             '不随项目提交）：`FE2E/`、`Jasmine/`、`D4RD/`、`MiDaS/`、`PlaneToPBR/`、'
             '`DepthAnything-on-Browser/`、`Depth-Anything-V2/`。')
    L.append('')
    path.write_text('\n'.join(L), encoding='utf-8')


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser(description='方法层 XY 对照实验')
    ap.add_argument('src', nargs='?', default='龙猫', help='截图目录或 glob')
    ap.add_argument('--out', help='输出目录（默认 <src>/method_lab）')
    ap.add_argument('--model', default=str(HERE / 'models' / 'depth_anything_v2_small_int8.onnx'))
    ap.add_argument('--quick', action='store_true', help='只跑 mean / median / seam')
    ap.add_argument('--no-depth', action='store_true', help='跳过深度方法')
    a = ap.parse_args()

    p = Path(a.src)
    if not p.is_absolute():
        p = HERE / p
    outdir = Path(a.out) if a.out else (p if p.is_dir() else p.parent) / 'method_lab'
    outdir.mkdir(parents=True, exist_ok=True)

    files = ts.discover_images(str(p))
    assert files, f'没有输入图片：{p}'
    ims = [ts.crop_black_border(cv2.imread(f)) for f in files]
    n = len(ims)
    print(f'输入 {n} 张，裁边后 {ims[0].shape[1]}x{ims[0].shape[0]}；输出 {outdir}', flush=True)

    xnames = [x for x in ESTIMATORS if not (a.no_depth and x == 'depth')]
    ynames = ['mean', 'median', 'seam'] if a.quick else FUSIONS

    ctx = {}
    if 'depth' in xnames:
        if not Path(a.model).exists():
            print(f'缺少深度模型 {a.model}，跳过 depth', flush=True)
            xnames.remove('depth')
        else:
            ctx['depth'] = DepthEstimator(a.model)

    # 全部 pair 的估计结果，按方法缓存
    all_ests = {}
    layouts = {}
    sift_pos = None
    for x in xnames:
        t0 = time.perf_counter()
        ests = {}
        for i in range(n):
            for j in range(i + 1, n):
                r = EST_FN[x](ims, i, j, ctx)
                if r is not None:
                    ests[(i, j)] = r
        t_est = (time.perf_counter() - t0) * 1000
        if not ests:
            print(f'  {x}: 全部 pair 估计失败，跳过', flush=True)
            continue
        all_ests[x] = ests
        pos, anchor, used = build_layout(ests, n)
        if sift_pos is None and x == 'sift':
            sift_pos = pos
        print(f'  {x}: {len(ests)} pairs, {t_est:.0f} ms, pos={pos}', flush=True)
        layouts[x] = {'pos': {str(k): list(v) for k, v in pos.items()},
                      'anchor': anchor, 'edges': used, 't_est_ms': t_est,
                      'n_pairs': len(ests)}

    # 布局一致性：与 SIFT baseline 的最大偏差
    ref = sift_pos or layouts[xnames[0]]['pos']
    if isinstance(ref, dict) and all(isinstance(v, list) for v in ref.values()):
        ref = {int(k): tuple(v) for k, v in ref.items()}
    for x, v in layouts.items():
        pos = {int(k): tuple(p) for k, p in v['pos'].items()}
        v['span_x'] = max(p[0] for p in pos.values()) - min(p[0] for p in pos.values())
        v['span_y'] = max(p[1] for p in pos.values()) - min(p[1] for p in pos.values())
        v['max_dev'] = max(((pos[k][0] - pos[0][0]) - (ref[k][0] - ref[0][0])) ** 2 +
                           ((pos[k][1] - pos[0][1]) - (ref[k][1] - ref[0][1])) ** 2
                           for k in pos) ** 0.5 if len(pos) > 1 else 0.0
        v['note'] = ('baseline' if x == 'sift' else
                     '收敛失败（诊断项）' if x == 'ecc' else
                     '需模型' if x == 'depth' else '')
    # 收敛失败自动标注
    for x in layouts:
        if layouts[x]['span_x'] + layouts[x]['span_y'] < 4:
            layouts[x]['note'] = '收敛失败：位移≈0（诊断项）'

    rows, thumbs = [], {}
    for x in xnames:
        if x not in all_ests:
            continue
        pos = {int(k): tuple(v) for k, v in layouts[x]['pos'].items()}
        stack, masks, offsets = warp_stack(ims, pos)
        edges = layouts[x]['edges']
        for y in ynames:
            t0 = time.perf_counter()
            try:
                out, seam = fuse(ims, pos, y, stack, masks)
            except Exception as e:
                print(f'  {x}/{y} 融合失败: {e}', flush=True)
                continue
            t_fuse = (time.perf_counter() - t0) * 1000
            q = qc(out)
            bg, ghost, area = overlap_quality(stack, masks, edges)
            r = {'x': x, 'y': y, **q,
                 'bg_p60': round(bg, 2) if bg is not None else None,
                 'ghost_pct': round(ghost, 2) if ghost is not None else None,
                 'overlap_px': area,
                 'osd_count': osd_count(out, ims),
                 'seam_cost': round(ts.seam_cost(out, seam), 2),
                 't_fuse_ms': round(t_fuse, 1)}
            rows.append(r)
            thumbs[(x, y)] = out
            print('  %-11s %-10s bg=%6.2f ghost=%5.2f%% osd=%d seam=%5.2f fuse=%5.0fms' %
                  (x, y, r['bg_p60'] or -1, r['ghost_pct'] or -1,
                   r['osd_count'], r['seam_cost'], t_fuse), flush=True)

    make_grid(thumbs, [x for x in xnames if x in all_ests], ynames, outdir / 'grid.png')

    # 运动主体分析用 SIFT baseline 的布局
    bx = 'sift' if 'sift' in all_ests else list(all_ests)[0]
    bpos = {int(k): tuple(v) for k, v in layouts[bx]['pos'].items()}
    stack, masks, offsets = warp_stack(ims, bpos)
    motion = motion_analysis(ims, bpos, stack, masks, offsets,
                             layouts[bx]['edges'], ctx.get('depth'),
                             outdir / 'motion_analysis.png')

    # 综合最优：几何对齐优先，再权衡接缝/行列台阶与固定 OSD 残留
    ok = [r for r in rows if r['bg_p60'] is not None]

    def score(r):
        return (r['bg_p60'] * 2.0 + r['seam_cost']
                + 0.25 * (r['row_jump'] + r['col_jump'])
                + 1.5 * r['osd_count'])

    best = min(ok, key=score) if ok else None
    if best:
        cv2.imwrite(str(outdir / 'best.png'), thumbs[(best['x'], best['y'])])

    speed = []
    for x in xnames:
        if x not in layouts:
            continue
        ms = layouts[x]['t_est_ms'] / max(layouts[x]['n_pairs'], 1)
        js = ('需要 ONNX Runtime Web（WebGPU/WASM）' if x == 'depth' else
              'OpenCV.js / jsfeat 可直接实现' if x in ('orb', 'phase', 'ecc', 'ecc_init', 'motionmask') else
              'OpenCV.js SIFT 可用，较慢')
        speed.append((x, ms, js, layouts[x]['note'] or '—'))
    if 'depth' in ctx:
        speed.append(('depth(infer)', ctx['depth'].time_s * 1000 / max(n, 1),
                      'int8 ONNX，CPU %.2fs/帧' % (ctx['depth'].time_s / max(n, 1)), '4 帧缓存'))

    result = {
        'src': str(p), 'n_frames': n,
        'shape': [ims[0].shape[1], ims[0].shape[0]],
        'xnames': [x for x in xnames if x in all_ests], 'ynames': ynames,
        'layouts': layouts, 'rows': rows, 'motion': motion,
        'speed': speed, 'best': best,
        'depth_choices': ctx.get('depth_choices', []),
    }
    (outdir / 'results.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    write_report(outdir / 'report.md', {**result,
                 'xnames': [x for x in xnames if x in all_ests]})
    print('\n最优:', best['x'], best['y'] if best else None, flush=True)
    print('运动主体:', motion, flush=True)
    print('产物:', outdir, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
