#!/usr/bin/env python3
"""动漫截图拼接：一条命令跑完「拼接 → 清理 → 质检」。

    python3 collage.py 亚丝娜镜头1
    python3 collage.py "frames/*.png" --out result/ --model models/lama_fp32.onnx
    python3 collage.py 亚丝娜镜头1 --skip-stitch        # 只重跑清理+质检
    python3 collage.py --selftest                       # 光度补偿合成自检

产物（都在 --out 目录，默认与输入同目录）：
    translate_stitched_raw.png    未裁边的原始拼接画布
    translate_stitched.png        裁掉黑边后的拼接图
    translate_stitched_clean.png  清理黑块、修复接缝后的最终图
    seam_mask.png                 GraphCut 接缝位置
    qc_report.json                黑区占比 / 行、列亮度跳变等质检指标

无硬编码绝对路径；模型默认取脚本同目录 models/lama_fp32.onnx。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clean_stitched as cs          # noqa: E402
import translate_stitch as ts       # noqa: E402


# ---------------------------------------------------------------- 质检
def qc(im):
    """黑区残留、整体亮度、横向/纵向亮度台阶。数值越小越干净。"""
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    row = np.abs(np.diff(g.mean(axis=1)))
    col = np.abs(np.diff(g.mean(axis=0)))
    return {
        "size": [int(im.shape[1]), int(im.shape[0])],
        "mean_luma": round(float(g.mean()), 2),
        "uncovered_black_pct": round(float((im.max(axis=2) < 8).mean() * 100), 4),
        "max_row_jump": round(float(row.max()), 2),
        "max_row_jump_at": int(row.argmax()),
        "max_col_jump": round(float(col.max()), 2),
        "max_col_jump_at": int(col.argmax()),
    }


def print_report(rep):
    print("\n=== 质检报告 ===")
    print(f"{'阶段':<10}{'尺寸':<14}{'均值':>8}{'黑区%':>9}{'行跳变':>10}{'列跳变':>10}")
    for k, v in rep.items():
        w, h = v["size"]
        print(f"{k:<10}{f'{w}x{h}':<14}{v['mean_luma']:>8.1f}"
              f"{v['uncovered_black_pct']:>9.3f}{v['max_row_jump']:>10.2f}"
              f"{v['max_col_jump']:>10.2f}")
    if "raw" in rep and "clean" in rep:
        a, b = rep["raw"], rep["clean"]
        print(f"\n黑区 {a['uncovered_black_pct']:.3f}% -> {b['uncovered_black_pct']:.3f}%  |  "
              f"行跳变 {a['max_row_jump']:.2f} -> {b['max_row_jump']:.2f}  |  "
              f"列跳变 {a['max_col_jump']:.2f} -> {b['max_col_jump']:.2f}")


# ---------------------------------------------------------------- 自检
def selftest():
    """合成三帧不同曝光的平移序列，验证 exposure_chain 能消掉重叠区光度差。"""
    rng = np.random.default_rng(7)
    base = rng.integers(20, 235, (400, 300, 3), dtype=np.uint8).astype(np.float32)
    shift, fh, canvas_h = 60, 200, 320
    exposures = [(1.00, 0.0), (0.82, 18.0), (1.15, -12.0)]
    src, masks = [], []
    for k, (g0, o0) in enumerate(exposures):
        s = np.zeros((canvas_h, 300, 3), np.float32)
        m = np.zeros((canvas_h, 300), np.uint8)
        y = k * shift
        s[y:y + fh] = base[k * shift:k * shift + fh] * g0 + o0
        m[y:y + fh] = 255
        src.append(s)
        masks.append(m)

    def overlap_mae(a, b):
        ov = (masks[a] > 0) & (masks[b] > 0)
        return float(np.abs(src[a][ov] - src[b][ov]).mean())

    before = [overlap_mae(0, 1), overlap_mae(1, 2)]
    chain = ts.exposure_chain(src, masks, verbose=False)
    for k, (g0, o0) in enumerate(chain):
        keep = (masks[k] > 0)[..., None]
        src[k] = np.where(keep, src[k] * g0 + o0, src[k])
    after = [overlap_mae(0, 1), overlap_mae(1, 2)]
    print("重叠区 MAE（帧0-1 / 帧1-2）")
    print(f"  补偿前: {before[0]:.2f} / {before[1]:.2f}")
    print(f"  补偿后: {after[0]:.2f} / {after[1]:.2f}")
    ok = all(b > 0.1 and a < b * 0.6 for a, b in zip(after, before))
    print("自检", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="动漫截图拼接：拼接 → 清理 → 质检")
    ap.add_argument('src', nargs='?', help='截图目录 或 glob（如 "frames/*.png"）')
    ap.add_argument('--out', help='输出目录（默认与输入同目录）')
    ap.add_argument('--model', help='LaMa onnx 路径')
    ap.add_argument('--mode', choices=['seam', 'multiband', 'feather'], default='seam')
    ap.add_argument('--photometry', choices=['auto', 'on', 'off'], default='auto',
                    help='逐帧曝光补偿：auto=按接缝台阶 A/B 自动选择（默认），on/off=强制')
    ap.add_argument('--no-clean', action='store_true', help='只拼接，不清理')
    ap.add_argument('--skip-stitch', action='store_true', help='用已有 raw 只跑清理+质检')
    ap.add_argument('--selftest', action='store_true', help='光度补偿合成自检，不读图片')
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.src:
        ap.error('需要输入目录或 glob（或用 --selftest）')

    p = Path(a.src)
    outdir = Path(a.out) if a.out else (p if p.is_dir() else p.parent)
    outdir.mkdir(parents=True, exist_ok=True)

    if not a.skip_stitch:
        files = ts.discover_images(a.src)
        if not files:
            ap.error(f'没有找到输入图片：{a.src}')
        ts.stitch_files(files, str(outdir), mode=a.mode,
                        photometry=a.photometry)

    raw = outdir / 'translate_stitched_raw.png'
    clean_path = outdir / 'translate_stitched_clean.png'
    if not a.no_clean:
        if not raw.exists():
            ap.error(f'缺少 {raw}；请先跑一次完整流程或去掉 --skip-stitch')
        print('== 清理', raw)
        cs.clean(str(raw), str(clean_path), model=a.model)

    rep = {}
    for name, fp in [('stitched', outdir / 'translate_stitched.png'),
                     ('raw', raw), ('clean', clean_path)]:
        if fp.exists():
            rep[name] = qc(cv2.imread(str(fp)))
    (outdir / 'qc_report.json').write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    print_report(rep)
    print('\n质检数据:', outdir / 'qc_report.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
