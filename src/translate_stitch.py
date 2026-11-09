"""黑盒无损平移拼接（自动排序，无任何顺序/上下特调）。

设计目标：代码对输入图片"无知"。给定一组图片（任意顺序），它自行：
  1) SIFT 估计两两平移并判断哪些对重叠；
  2) 用重叠关系构建图，BFS 自动布局——谁上谁下由重叠关系决定，而非人工指定；
  3) 把每图按全局平移量"累积放置"到画布（只平移、无透视/仿射 warp）→ 零形状扭曲；
  4) 重叠区有效区平均，裁黑边。

输入：目录下所有 `image.*.png`（默认，任意顺序）
输出：translate_stitched.png（无损、零形状扭曲的拼接大图）

`--demo` 额外演示"任意方向平移的楼梯锯齿无损拼接"：取已有图作场景，
沿左上 45° 切窗生成平移序列（同样黑盒输入），用同一 auto_layout 拼回 → staircase_demo.png。
"""
import cv2, numpy as np, os, glob, sys
from collections import deque

d = '/workspace/anime'


def crop_black_border(im, thresh=18, ratio=0.5):
    """保守裁掉四周纯黑边框（视频 letterbox / 字幕条）。无黑边则原样返回。

    用"列/行非黑像素比例 > ratio"定位内容区；只在确有黑边时裁，
    避免误裁正常图影响后续。返回 (裁剪图, (x0,y0,x1,y1))。
    """
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    nb = (g > thresh).astype(np.float32)
    cs = np.where(nb.mean(axis=0) > ratio)[0]
    rs = np.where(nb.mean(axis=1) > ratio)[0]
    if len(cs) < 2 or len(rs) < 2:
        return im
    x0, x1 = int(cs.min()), int(cs.max())
    y0, y1 = int(rs.min()), int(rs.max())
    # 边界几乎贴合原图 → 视为无黑边
    if x0 <= 1 and y0 <= 1 and x1 >= im.shape[1] - 2 and y1 >= im.shape[0] - 2:
        return im
    return im[y0:y1 + 1, x0:x1 + 1]


def trim_dark_edges(img, thresh=25, ratio=0.35, max_px=16):
    """裁掉输出图四周的整行/整列暗边（黑线）。

    旧实现用「整行均值 < thresh」判断，而拼接残留的黑线常常只占行的一部分，
    均值仍在 30~60 之间（实测镜头1 首行 34.9、末行 53.9），于是裁不掉、
    在成图上留下一条 1px 黑线。这里改成按「近黑像素占比」判断。
    """
    def dark_frac(line):
        px = line if line.ndim == 1 else line.mean(axis=1)
        return float((px < thresh).mean())

    for _ in range(max_px):
        if img.shape[0] <= 4 or img.shape[1] <= 4:
            break
        edges = {
            "top": dark_frac(img[0]),
            "bottom": dark_frac(img[-1]),
            "left": dark_frac(img[:, 0]),
            "right": dark_frac(img[:, -1]),
        }
        hit = [k for k, v in edges.items() if v >= ratio]
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


def _gray_clahe(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(g)


def _match_pt_ransac(g1, g2):
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(g1, None)
    kp2, des2 = sift.detectAndCompute(g2, None)
    if des1 is None or des2 is None:
        return None
    m = cv2.BFMatcher().knnMatch(des1, des2, k=2)
    good = [a for a, b in m if a.distance < 0.8 * b.distance]
    if len(good) < 6:
        return None
    src = np.float32([kp1[a.queryIdx].pt for a in good])
    dst = np.float32([kp2[a.trainIdx].pt for a in good])
    sx = dst[:, 0] - src[:, 0]; sy = dst[:, 1] - src[:, 1]
    rng = np.random.default_rng(0)
    best_n, best = 0, (0.0, 0.0)
    for _ in range(3000):
        i = int(rng.integers(len(src)))
        dx = float(sx[i]); dy = float(sy[i])
        n = int((np.abs(sx - dx) + np.abs(sy - dy) < 4.0).sum())
        if n > best_n:
            best_n = n; best = (dx, dy)
    if best_n < 6:
        return None
    return (best[0], best[1], best_n, len(good))


def est_translation(im1, im2):
    """估计 im2 相对 im1 的平移 (dx,dy) 与内点数。

    自适应：原图灰度和 CLAHE 增强各算一次，取内点数更多的。
    - 镜头1（冰晶高对比）：CLAHE 内点更多 → 找回真实垂直位移；
    - 镜头2（水雾低对比）：原图内点更多 → 避免 CLAHE 放大的"位移0"假匹配。
    """
    gl1 = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    gl2 = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)
    r_orig = _match_pt_ransac(gl1, gl2)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    r_clahe = _match_pt_ransac(clahe.apply(gl1), clahe.apply(gl2))
    cands = [r for r in (r_orig, r_clahe) if r]
    if not cands:
        return None
    # 按「内点率」选更可靠的（水纹理经 CLAHE 后 ninl 可能很大，但内点率低）
    best = max(cands, key=lambda r: r[2] / max(r[3], 1))
    return (best[0], best[1], best[2])


def auto_layout(ims, min_matches=6):
    """用「最大生成树」自动布局：返回每张图全局位置（顺序无关）。

    用内点数作边权做 Kruskal MST：强边优先，避免淡图/重复纹理的弱边把位置拉错
    （例如镜头2 若从淡图0 走弱边，会把图1/2 都拉到位移0；MST 会优先用强边 图1-图2）。
    """
    n = len(ims)
    T = {}
    for i in range(n):
        for j in range(i + 1, n):
            r = est_translation(ims[i], ims[j])
            if r and r[2] >= min_matches:
                T[(i, j)] = r          # (dx,dy,ninl)
    if not T:
        raise RuntimeError("未找到任何重叠对，无法拼接")
    edges = sorted(T.items(), key=lambda kv: kv[1][2], reverse=True)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    adj = {i: [] for i in range(n)}
    for (i, j), (dx, dy, ninl) in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            adj[i].append((j, dx, dy))
            adj[j].append((i, -dx, -dy))
    anchor = edges[0][0][0] if edges else 0
    pos = {anchor: (0.0, 0.0)}
    q = deque([anchor])
    while q:
        i = q.popleft()
        for j, dx, dy in adj[i]:
            if j not in pos:
                pos[j] = (pos[i][0] - dx, pos[i][1] - dy)
                q.append(j)
    for i in range(n):              # 不连通图兜底
        if i not in pos:
            pos[i] = (0.0, 0.0)
    return pos, anchor


def accumulate(ims, pos):
    """按全局位置累积平移放置（亚像素 warpAffine 纯平移，仅插值不扭曲形状）。

    注意：pos 是 {索引: (x,y)} 的 dict，其 .values() 顺序不一定等于 ims 列表索引，
    必须显式按索引 [pos[i] for i in range(n)] 取位置，否则图与位置会错配。
    """
    positions = [pos[i] for i in range(len(ims))]
    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]
    minx, miny = min(xs), min(ys)
    maxx = max(p[0] + im.shape[1] for p, im in zip(positions, ims))
    maxy = max(p[1] + im.shape[0] for p, im in zip(positions, ims))
    W = int(np.ceil(maxx - minx)); H = int(np.ceil(maxy - miny))
    canvas = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    for im, (px, py) in zip(ims, positions):
        M = np.float32([[1, 0, px - minx], [0, 1, py - miny]])
        warped = cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
        alpha = cv2.warpAffine(np.ones(im.shape[:2], np.float32), M, (W, H),
                               flags=cv2.INTER_LINEAR, borderValue=0)
        canvas += warped * alpha[..., None]
        wsum += alpha[..., None]
    canvas /= np.maximum(wsum, 1e-6)
    mask = wsum[:, :, 0] > 0.5
    ys_, xs_ = np.where(mask)
    return canvas[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1].astype(np.uint8)


def accumulate_blend(ims, pos, use_multiband=True):
    """用 OpenCV detail 的融合器（MultiBand / Feather）替代简单平均，消除接缝细线。

    借鉴 OpenCV Stitcher 源码中的 MultiBandBlender（拉普拉斯金字塔多频段融合）：
    每图仅做纯平移 warp，再送入融合器做重叠区加权混合 —— 仍零形状扭曲，但接缝更平滑。
    """
    valid = [i for i in range(len(ims)) if i in pos]
    ims = [ims[i] for i in valid]
    n = len(ims)
    positions = [pos[i] for i in valid]
    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]
    minx, miny = min(xs), min(ys)
    # 全景 roi（含亚像素余量）
    maxx = max((p[0] - minx) + im.shape[1] for p, im in zip(positions, ims))
    maxy = max((p[1] - miny) + im.shape[0] for p, im in zip(positions, ims))
    W = int(np.ceil(maxx)); H = int(np.ceil(maxy))
    corners = [(int(round(px - minx)), int(round(py - miny))) for px, py in positions]
    sizes = [(int(im.shape[1]), int(im.shape[0])) for im in ims]
    if use_multiband:
        blender = cv2.detail.MultiBandBlender()
    else:
        blender = cv2.detail.FeatherBlender()
        blender.setSharpness(0.002)
    blender.prepare((0, 0, W, H))
    for k, (im, (px, py)) in enumerate(zip(ims, positions)):
        cx, cy = corners[k]
        # 整数 corner 定大位置；亚像素残差在单图内微调（仅边缘 <1px 黑边，不影响重叠区）
        dx = (px - minx) - cx
        dy = (py - miny) - cy
        Msub = np.float32([[1, 0, dx], [0, 1, dy]])
        warped = cv2.warpAffine(im, Msub, (im.shape[1], im.shape[0]),
                               flags=cv2.INTER_LINEAR, borderValue=0)
        wmask = cv2.warpAffine(np.ones(im.shape[:2], np.uint8) * 255, Msub,
                               (im.shape[1], im.shape[0]),
                               flags=cv2.INTER_LINEAR, borderValue=0)
        blender.feed(warped.astype(np.int16), wmask, corners[k])
    result = np.zeros((H, W, 3), np.int16)
    result_mask = np.zeros((H, W, 1), np.uint8)
    result, result_mask = blender.blend(result, result_mask)
    result = result.astype(np.float32)
    mask = result_mask[:, :, 0] > 0
    ys_, xs_ = np.where(mask)
    out = result[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1]
    return np.clip(out, 0, 255).astype(np.uint8)


def accumulate_seam(ims, pos):
    """用 GraphCutSeamFinder 沿内容找最优接缝（而非矩形边），再按归属合成。

    这是 OpenCV Stitcher 源码中 seam_finders.cpp 的思路：在重叠区用最小割
    （颜色/梯度代价）选一条接缝路径，让边界藏在人物/建筑等内容边缘，避免水平硬线。
    """
    valid = [i for i in range(len(ims)) if i in pos]
    ims = [ims[i] for i in valid]
    n = len(ims)
    positions = [pos[i] for i in valid]
    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]
    minx, miny = min(xs), min(ys)
    maxx = max((p[0] - minx) + im.shape[1] for p, im in zip(positions, ims))
    maxy = max((p[1] - miny) + im.shape[0] for p, im in zip(positions, ims))
    W = int(np.ceil(maxx)); H = int(np.ceil(maxy))
    src, masks = [], []
    for im, (px, py) in zip(ims, positions):
        M = np.float32([[1, 0, px - minx], [0, 1, py - miny]])
        warped = cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_LINEAR,
                               borderValue=0).astype(np.float32)
        m = cv2.warpAffine(np.ones(im.shape[:2], np.uint8) * 255, M, (W, H),
                          flags=cv2.INTER_LINEAR, borderValue=0)
        src.append(warped); masks.append(m)
    # 光度（曝光/颜色）补偿：把各图在重叠区的通道均值对齐到参考图，减少亮度/色差接缝
    if len(src) > 1:
        ref = src[0]; refm = masks[0] > 0
        for k in range(1, len(src)):
            ov = (masks[k] > 0) & refm
            if ov.sum() > 200:
                for c in range(3):
                    g = float(ref[ov][:, c].mean()) / max(float(src[k][ov][:, c].mean()), 1e-3)
                    src[k][:, :, c] *= np.clip(g, 0.5, 2.0)
    corners = [(0, 0)] * n
    finder = cv2.detail.GraphCutSeamFinder('COST_COLOR_GRAD')
    # 大图图割很慢：在 1/4 分辨率找接缝，再上采样 mask（加速 ~16x）
    sc = 0.25
    sw, sh = max(1, int(W * sc)), max(1, int(H * sc))
    src_s = [cv2.resize(s, (sw, sh), interpolation=cv2.INTER_AREA) for s in src]
    masks_s = [cv2.resize(m, (sw, sh), interpolation=cv2.INTER_NEAREST) for m in masks]
    masks_s = finder.find(src_s, corners, masks_s)
    masks = [cv2.resize((m.get() if hasattr(m, 'get') else m), (W, H),
                        interpolation=cv2.INTER_NEAREST) for m in masks_s]
    result = np.zeros((H, W, 3), np.float32)
    acc = np.zeros((H, W, 1), np.float32)
    for warped, m in zip(src, masks):
        mm = (m > 0)[..., None].astype(np.float32)
        result += warped * mm
        acc += mm
    result /= np.maximum(acc, 1e-6)
    # 接缝 mask：归属图变化处（膨胀 41px），供 LaMa inpainting 修复
    mstack = np.stack([(m > 0).astype(np.uint8) for m in masks], axis=0)
    labels = np.argmax(mstack, axis=0)
    valid = mstack.max(axis=0) > 0
    seam = np.zeros((H, W), np.uint8)
    seam[:-1, :] |= ((labels[:-1, :] != labels[1:, :]) & valid[:-1, :] & valid[1:, :]).astype(np.uint8)
    seam[:, :-1] |= ((labels[:, :-1] != labels[:, 1:]) & valid[:, :-1] & valid[:, 1:]).astype(np.uint8)
    seam = cv2.dilate(seam * 255, np.ones((11, 11), np.uint8))
    mask = acc[:, :, 0] > 0.5
    ys_, xs_ = np.where(mask)
    y0, y1, x0, x1 = ys_.min(), ys_.max() + 1, xs_.min(), xs_.max() + 1
    out = result[y0:y1, x0:x1]
    seam = seam[y0:y1, x0:x1]
    return np.clip(out, 0, 255).astype(np.uint8), seam


def make_staircase_demo():
    """演示：任意方向（左上45°）平移镜头的楼梯锯齿无损拼接。"""
    base = cv2.imread(os.path.join(d, 'stitched_final.png'))
    H, W = base.shape[:2]
    wh, ww, s = 420, 420, 140
    frames = []
    x, y = W - ww, H - wh
    while x >= 0 and y >= 0:
        frames.append(base[y:y + wh, x:x + ww].copy())
        x -= s; y -= s
    # 打乱顺序，证明 auto_layout 不依赖输入次序（黑盒）
    import random
    random.seed(0); random.shuffle(frames)
    pos, _ = auto_layout(frames)
    demo = accumulate_blend(frames, pos)
    cv2.imwrite(os.path.join(d, 'staircase_demo.png'), demo)
    print("staircase_demo.png  frames=", len(frames), " shape", demo.shape)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if args and os.path.isdir(args[0]):
        outdir = args[0]
        files = sorted(glob.glob(os.path.join(outdir, '*.png')))
    else:
        outdir = d
        pat = args[0] if args else 'image.*.png'
        files = sorted(glob.glob(os.path.join(d, pat)))
    _skip = ('translate_stitched', 'seam_mask', 'compare_inpaint')
    files = [f for f in files if not any(k in os.path.basename(f) for k in _skip)]
    assert files, "no image files found"
    ims = [crop_black_border(cv2.imread(f)) for f in files]
    print(f"输入 {len(ims)} 张（顺序无关，黑盒）：")
    for f in files:
        print("  ", os.path.basename(f))
    pos, anchor = auto_layout(ims)
    print("自动布局（谁上谁下由重叠关系决定，anchor=", os.path.basename(files[anchor]), "）：", pos)
    # 同帧去重：位移<2px 的图组只保留最清晰的一张（避免淡图覆盖清晰图）
    keep = list(range(len(ims)))
    if len(ims) > 1:
        for i in range(len(ims)):
            for j in range(i + 1, len(ims)):
                if i in keep and j in keep and \
                   abs(pos[i][0] - pos[j][0]) + abs(pos[i][1] - pos[j][1]) < 2.0:
                    si = float(cv2.Laplacian(cv2.cvtColor(ims[i], cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                    sj = float(cv2.Laplacian(cv2.cvtColor(ims[j], cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                    keep.remove(j if si >= sj else i)
    if len(keep) < len(ims):
        print(f"同帧去重：{len(ims)} -> {len(keep)} 张（保留更清晰）")
        ims = [ims[k] for k in keep]
        pos = {n: pos[k] for n, k in enumerate(keep)}
    # 自动判断：若所有图几乎同帧（位移跨度极小），拼接无意义 → 选最清晰的一张
    pv = [pos[i] for i in pos]
    span = (max(max(p[0] for p in pv) - min(p[0] for p in pv),
                max(p[1] for p in pv) - min(p[1] for p in pv)) if pv else 0)
    if span < 4.0:
        print(f"检测到几乎同帧（位移跨度 {span:.2f}px），拼接无意义 → 自动选最清晰的一张")
        sharp = [float(cv2.Laplacian(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                 for im in ims]
        best = int(np.argmax(sharp))
        print("  最优帧:", os.path.basename(files[best]), "sharpness", round(sharp[best], 1))
        out = trim_dark_edges(crop_black_border(ims[best]))
        cv2.imwrite(os.path.join(outdir, 'translate_stitched.png'), out)
        print(os.path.join(outdir, 'translate_stitched.png'), out.shape)
        return
    # 默认自动：GraphCut 接缝（效果最好，内部 1/4 下采样加速），输入无需任何参数；
    # --multiband / --feather / --seam 作为技术手段单独保留。
    if '--multiband' in sys.argv:
        out = accumulate_blend(ims, pos, use_multiband=True)
        name = 'translate_stitched_multiband.png'
    elif '--feather' in sys.argv:
        out = accumulate_blend(ims, pos, use_multiband=False)
        name = 'translate_stitched_feather.png'
    else:  # 默认 & --seam：自动图割接缝
        out, seam = accumulate_seam(ims, pos)
        cv2.imwrite(os.path.join(outdir, 'translate_stitched_raw.png'), out)
        cv2.imwrite(os.path.join(outdir, 'seam_mask.png'), seam)
        name = 'translate_stitched.png'
    out = trim_dark_edges(crop_black_border(out))
    cv2.imwrite(os.path.join(outdir, name), out)
    print(os.path.join(outdir, name), out.shape)
    if '--demo' in sys.argv:
        make_staircase_demo()


if __name__ == '__main__':
    main()
