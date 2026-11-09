"""用 LaMa（ONNX，CPU）修复拼接接缝。

输入：<dir>/translate_stitched_raw.png + seam_mask.png（由 translate_stitch.py 的 --seam/默认 生成）
输出：<dir>/translate_stitched_inpaint.png（接缝用 LaMa 重绘）+ compare_inpaint.png

LaMa ONNX 固定输入 512x512：整图缩放推理后，只把 mask（接缝带）区域回填，非接缝区保持原图清晰。
"""
import cv2, numpy as np, os, sys
import onnxruntime as ort

d = sys.argv[1] if len(sys.argv) > 1 else '/workspace/anime/亚丝娜镜头2'
MODEL = '/workspace/anime/models/lama_fp32.onnx'


def lama_inpaint(img, mask, sess, size=512, stride=256):
    """512×512 分块修复接缝带（避免大 bbox 拉伸失真），只回填 mask 区域。"""
    H, W = img.shape[:2]
    res = img.copy()
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return img
    y0g, y1g = int(ys.min()), int(ys.max()) + 1
    x0g, x1g = int(xs.min()), int(xs.max()) + 1
    ystart = max(0, y0g - size // 2)
    xstart = max(0, x0g - size // 2)
    for y in range(ystart, y1g, stride):
        for x in range(xstart, x1g, stride):
            y1 = min(H, y + size); x1 = min(W, x + size)
            y0c = max(0, y1 - size); x0c = max(0, x1 - size)
            subm = mask[y0c:y1, x0c:x1]
            if (subm > 0).sum() < 20:
                continue
            sub = img[y0c:y1, x0c:x1]
            h, w = sub.shape[:2]
            rgb = cv2.cvtColor(sub, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            small = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
            m = cv2.resize(subm, (size, size), interpolation=cv2.INTER_NEAREST)
            m = (m > 0).astype(np.float32)
            out = sess.run(None, {'image': small.transpose(2, 0, 1)[None],
                                  'mask': m[None, None]})[0][0].transpose(1, 2, 0)
            out = np.clip(out * 255, 0, 255).astype(np.uint8)
            out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
            out_sub = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
            region = res[y0c:y1, x0c:x1]
            mm = subm > 0
            region[mm] = out_sub[mm]
            res[y0c:y1, x0c:x1] = region
    return res


def main():
    raw = cv2.imread(os.path.join(d, 'translate_stitched_raw.png'))
    mask = cv2.imread(os.path.join(d, 'seam_mask.png'), 0)
    assert raw is not None and mask is not None, \
        "需要先运行 translate_stitch.py 生成 translate_stitched_raw.png 与 seam_mask.png"
    sess = ort.InferenceSession(MODEL, providers=['CPUExecutionProvider'])
    res = lama_inpaint(raw, mask, sess)
    from translate_stitch import crop_black_border, trim_dark_edges
    res = trim_dark_edges(crop_black_border(res))
    cv2.imwrite(os.path.join(d, 'translate_stitched_inpaint.png'), res)
    print('saved', os.path.join(d, 'translate_stitched_inpaint.png'), res.shape)
    base = cv2.imread(os.path.join(d, 'translate_stitched.png'))
    if base is not None:
        h = min(base.shape[0], res.shape[0]); w = min(base.shape[1], res.shape[1])
        cmp = np.hstack([base[:h, :w], res[:h, :w]])
        cv2.imwrite(os.path.join(d, 'compare_inpaint.png'), cmp)
        print('saved', os.path.join(d, 'compare_inpaint.png'))


if __name__ == '__main__':
    main()
