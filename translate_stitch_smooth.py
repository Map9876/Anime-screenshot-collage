"""无损平移累积拼接（亚像素版）：纯平移 warp + 有效区平均。

相比 translate_stitch.py 的整数取整，本版用亚像素平移矩阵（只平移、无旋转/透视/缩放），
消除重叠区因取整产生的细缝。亚像素重采样仅带来极轻微插值，不改变形状。

输出：translate_stitched_smooth.png
"""
import cv2, numpy as np, os

d = '/workspace/anime'


def est_translation(im1, im2):
    sift = cv2.SIFT_create()
    g1 = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)
    kp1, des1 = sift.detectAndCompute(g1, None)
    kp2, des2 = sift.detectAndCompute(g2, None)
    bf = cv2.BFMatcher()
    m = bf.knnMatch(des1, des2, k=2)
    good = [a for a, b in m if a.distance < 0.75 * b.distance]
    src = np.float32([kp1[a.queryIdx].pt for a in good])
    dst = np.float32([kp2[a.trainIdx].pt for a in good])
    return float(np.median(dst[:, 0] - src[:, 0])), float(np.median(dst[:, 1] - src[:, 1]))


def accumulate_subpixel(ims, placements):
    n = len(ims)
    pos = [(0.0, 0.0)]
    for k in range(1, n):
        dx, dy = placements[k - 1]
        pos.append((pos[k - 1][0] + dx, pos[k - 1][1] + dy))
    minx = min(p[0] for p in pos); miny = min(p[1] for p in pos)
    maxx = max(p[0] + im.shape[1] for im, p in zip(ims, pos))
    maxy = max(p[1] + im.shape[0] for im, p in zip(ims, pos))
    W = int(np.ceil(maxx - minx)); H = int(np.ceil(maxy - miny))
    canvas = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    for im, p in zip(ims, pos):
        M = np.float32([[1, 0, p[0] - minx], [0, 1, p[1] - miny]])
        warped = cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
        alpha = cv2.warpAffine(np.ones(im.shape[:2], np.float32), M, (W, H),
                               flags=cv2.INTER_LINEAR, borderValue=0)
        canvas += warped * alpha[..., None]
        wsum += alpha[..., None]
    canvas /= np.maximum(wsum, 1e-6)
    mask = wsum[:, :, 0] > 0.5
    ys_, xs_ = np.where(mask)
    canvas = canvas[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1]
    return canvas.astype(np.uint8)


a89 = cv2.imread(d + '/image.a89eba6335.png')
d84 = cv2.imread(d + '/image.d8464ec779.png')
foot = cv2.imread(d + '/image.6d2e71a026.png')
t1 = est_translation(a89, d84)
t2 = est_translation(d84, foot)
print("t1:", t1, " t2:", t2)
res = accumulate_subpixel([a89, d84, foot], [(-t1[0], -t1[1]), (-t2[0], -t2[1])])
cv2.imwrite(d + '/translate_stitched_smooth.png', res)
print("translate_stitched_smooth.png", res.shape)
