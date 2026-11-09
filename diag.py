import cv2, numpy as np, os, itertools

d = '/workspace/anime'
files = sorted([f for f in os.listdir(d) if f.lower().endswith('.png')])
imgs = [cv2.imread(os.path.join(d, f)) for f in files]
print("files:")
for f, im in zip(files, imgs):
    print("  ", f, None if im is None else im.shape)

sift = cv2.SIFT_create()
kps, dess = [], []
for im in imgs:
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    kp, de = sift.detectAndCompute(g, None)
    kps.append(kp); dess.append(de)
    print("  kp", len(kp))

bf = cv2.BFMatcher()
for i, j in itertools.combinations(range(len(imgs)), 2):
    if dess[i] is None or dess[j] is None:
        continue
    m = bf.knnMatch(dess[i], dess[j], k=2)
    good = [a for a, b in m if a.distance < 0.75 * b.distance]
    line = f"pair {i}-{j}: good={len(good)}"
    if len(good) >= 10:
        src = np.float32([kps[i][g.queryIdx].pt for g in good]).reshape(-1, 1, 2)
        dst = np.float32([kps[j][g.trainIdx].pt for g in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if H is not None:
            inl = int(mask.sum())
            line += f" inliers={inl} tx={H[0,2]:.1f} ty={H[1,2]:.1f} scale~{np.sqrt(H[0,0]**2+H[1,0]**2):.2f}"
    print(line)

try:
    st = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
    status, out = st.stitch(imgs)
    print("stitcher status", status)
    if status == cv2.Stitcher_OK:
        cv2.imwrite(os.path.join(d, 'stitched_auto.png'), out)
        print("saved stitched_auto.png", out.shape)
except Exception as e:
    print("stitcher err", e)
