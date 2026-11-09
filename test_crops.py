import cv2, numpy as np, os

d = '/workspace/anime'


def stitch(imgs, outname):
    st = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
    status, pano = st.stitch(imgs)
    if status == cv2.Stitcher_OK:
        cv2.imwrite(os.path.join(d, outname), pano)
        print(f"  => {outname}: OK  {pano.shape}")
    else:
        print(f"  => {outname}: FAILED  status={status}")
    return status


a89 = cv2.imread(d + '/image.a89eba6335.png')
d84 = cv2.imread(d + '/image.d8464ec779.png')
foot = cv2.imread(d + '/image.6d2e71a026.png')
print("original shapes (h,w):", a89.shape[:2], d84.shape[:2], foot.shape[:2])

# 测试 A：最底脚图 左侧 20% 裁掉
h, w = foot.shape[:2]
footA = foot[:, int(w * 0.2):, :]
cv2.imwrite(d + '/testA_foot_left20.png', footA)
print("testA: foot crop left20 ->", footA.shape[:2])
stitch([a89, d84, footA], 'testA_stitched.png')

# 测试 B：最底脚图 左侧 20% + 下方 20%（重合区）裁掉
footB = foot[:int(h * 0.8), int(w * 0.2):, :]
cv2.imwrite(d + '/testB_foot_left20_bottom20.png', footB)
print("testB: foot crop left20+bottom20 ->", footB.shape[:2])
stitch([a89, d84, footB], 'testB_stitched.png')
