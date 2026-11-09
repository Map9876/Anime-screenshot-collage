"""APAP（As-Projective-As-Possible）局部网格对齐 vs 全局单应 对比实验。

用合成视差对演示：当相邻图存在"前景相对背景的视差位移"时，全局单应无法同时对齐
背景与前景（产生重影），而 APAP 把图分成网格、逐顶点估计局部单应，可局部修正。

输出（/workspace/anime/）：
  synth_A.png / synth_B.png        合成视差对（B 右半相对 A 右移，模拟前景视差）
  baseline_global.png              全局单应拼接（背景对齐→前景重影）
  apap_result.png                  APAP 网格对齐拼接（前景也被对齐）
  compare.png                      并排对比
"""
import cv2, numpy as np, os

d = '/workspace/anime'


def get_matches(img1, img2):
    sift = cv2.SIFT_create()
    g1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    kp1, des1 = sift.detectAndCompute(g1, None)
    kp2, des2 = sift.detectAndCompute(g2, None)
    bf = cv2.BFMatcher()
    m = bf.knnMatch(des1, des2, k=2)
    good = [a for a, b in m if a.distance < 0.75 * b.distance]
    if len(good) < 10:
        return None
    src = np.float32([kp1[a.queryIdx].pt for a in good])   # 在 img1 坐标
    dst = np.float32([kp2[a.trainIdx].pt for a in good])   # 在 img2 坐标
    return src, dst


def apap_warp(img2, dst, src, H_global, grid=(10, 10), radius=0.6):
    """对 img2 做网格形变 warp 到 img1 空间。"""
    h, w = img2.shape[:2]
    gh, gw = grid
    vy = np.linspace(0, h, gh + 1)
    vx = np.linspace(0, w, gw + 1)
    disp = np.zeros((gh + 1, gw + 1, 2))  # 顶点 (du,dv)：img2->img1 位移

    ry = (h / gh) * radius * 2
    rx = (w / gw) * radius * 2
    for i in range(gh + 1):
        for j in range(gw + 1):
            cx, cy = vx[j], vy[i]
            # 先放全局位移
            p = np.array([cx, cy, 1.0]); q = H_global @ p; q = q[:2] / q[2]
            disp[i, j] = q[:2] - p[:2]
            # 用附近匹配点重估局部单应（APAP 核心）
            msk = (np.abs(dst[:, 0] - cx) < rx) & (np.abs(dst[:, 1] - cy) < ry)
            if msk.sum() >= 4:
                Hl, _ = cv2.findHomography(dst[msk], src[msk], cv2.RANSAC, 5.0)
                if Hl is not None:
                    p = np.array([cx, cy, 1.0]); q = Hl @ p; q = q[:2] / q[2]
                    disp[i, j] = q[:2] - p[:2]

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    fi = ys / (h / gh); fj = xs / (w / gw)
    i0 = np.clip(fi.astype(int), 0, gh - 1); j0 = np.clip(fj.astype(int), 0, gw - 1)
    i1 = np.clip(i0 + 1, 0, gh); j1 = np.clip(j0 + 1, 0, gw)
    wi = np.clip(fi - i0, 0, 1).reshape(h, w, 1)
    wj = np.clip(fj - j0, 0, 1).reshape(h, w, 1)
    d00, d01 = disp[i0, j0], disp[i0, j1]
    d10, d11 = disp[i1, j0], disp[i1, j1]
    dtop = d00 * (1 - wj) + d01 * wj
    dbot = d10 * (1 - wj) + d11 * wj
    D = dtop * (1 - wi) + dbot * wi
    mapx = (xs + D[..., 0]).astype(np.float32)
    mapy = (ys + D[..., 1]).astype(np.float32)
    return cv2.remap(img2, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ---------- 合成视差对 ----------
base = cv2.imread(d + '/stitched_final.png')
h, w = base.shape[:2]
A = base.copy()
B = base.copy()
dx = 50
x0 = int(w * 0.5)
# B 右半相对 A 右移 dx，模拟"前景相对背景的视差"
B[:, x0 + dx:] = base[:, x0:w - dx]
B[:, x0:x0 + dx] = base[:, x0:x0 + dx]
cv2.imwrite(d + '/synth_A.png', A)
cv2.imwrite(d + '/synth_B.png', B)
print("synth pair:", A.shape[:2], "dx=", dx)

# ---------- 匹配 + 全局单应 ----------
md = get_matches(A, B)
assert md is not None, "no matches"
src, dst = md
H_global, _ = cv2.findHomography(dst, src, cv2.RANSAC, 5.0)
print("H_global:\n", H_global)

# ---------- baseline：全局单应 warp + 平均融合 ----------
base_warp = cv2.warpPerspective(B, H_global, (w, h))
baseline = ((A.astype(float) + base_warp.astype(float)) / 2).astype(np.uint8)
cv2.imwrite(d + '/baseline_global.png', baseline)

# ---------- APAP：网格局部对齐 + 平均融合 ----------
apap_w = apap_warp(B, dst, src, H_global, grid=(12, 12))
apap = ((A.astype(float) + apap_w.astype(float)) / 2).astype(np.uint8)
cv2.imwrite(d + '/apap_result.png', apap)

# ---------- 并排对比图 ----------
def pad(im, H):
    if im.shape[0] < H:
        im = np.vstack([im, np.zeros((H - im.shape[0], im.shape[1], 3), np.uint8)])
    return im

top = np.hstack([A, B])
bot = np.hstack([baseline, apap])
H = max(top.shape[0], bot.shape[0])
top = pad(top, H); bot = pad(bot, H)
compare = np.vstack([
    np.hstack([cv2.putText(top.copy(), 'A (ref)', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2),
               cv2.putText(top.copy(), 'B (right-shifted dx=50, parallax)', (w+10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)]),
    np.hstack([cv2.putText(bot.copy(), 'Global Homography (ghost)', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2),
               cv2.putText(bot.copy(), 'APAP grid (fixed)', (w+10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)]),
])
cv2.imwrite(d + '/compare.png', compare)
print("saved: baseline_global.png, apap_result.png, compare.png")
