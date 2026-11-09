#!/usr/bin/env bash
# 一键下载 + 校验轻量深度模型（method_lab.py 的 depth / --depth-audit 用）。
#
#   bash setup_depth.sh            # 只下载 + 校验
#   bash setup_depth.sh --check    # 额外跑一次 518x518 推理自检（需 onnxruntime）
#
# 模型：HuggingFace onnx-community/depth-anything-v2-small 的 onnx/model_int8.onnx
#       原模型 depth-anything/Depth-Anything-V2-Small，Apache-2.0
#       27,258,801 B（26 MB），sha256 01aa7a23de3f4a0ee1a2bb9997e6918104c85a9f95dea46d27b9b3fb0c6b9001
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/models/depth_anything_v2_small_int8.onnx"
URL="https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_int8.onnx"
EXPECTED_SIZE=27258801
EXPECTED_SHA256="01aa7a23de3f4a0ee1a2bb9997e6918104c85a9f95dea46d27b9b3fb0c6b9001"
PYTHON="${PYTHON:-python3}"

mkdir -p "$(dirname "$OUT")"

if [[ ! -f "$OUT" ]]; then
  echo "[1/2] 下载 $URL"
  curl -L --fail --retry 3 --progress-bar -o "$OUT.part" "$URL"
  mv "$OUT.part" "$OUT"
else
  echo "[1/2] 已存在，跳过下载：$OUT"
fi

echo "[2/2] 校验"
size="$(stat -c %s "$OUT")"
sum="$(sha256sum "$OUT" | cut -d' ' -f1)"
[[ "$size" == "$EXPECTED_SIZE" ]] || { echo "大小不符：$size != $EXPECTED_SIZE"; exit 1; }
[[ "$sum" == "$EXPECTED_SHA256" ]] || { echo "SHA256 不符：$sum"; exit 1; }
echo "OK  $OUT"
echo "    $size bytes (26 MB)  sha256 $sum"

if [[ "${1:-}" == "--check" ]]; then
  echo "[extra] 推理自检"
  MODEL_PATH="$OUT" "$PYTHON" -c '
import os, numpy as np, onnxruntime as ort
s = ort.InferenceSession(os.environ["MODEL_PATH"], providers=["CPUExecutionProvider"])
i, o = s.get_inputs()[0], s.get_outputs()[0]
print("  ORT", ort.__version__)
print("  输入", i.name, i.shape, i.type)
print("  输出", o.name, o.shape)
y = s.run(None, {i.name: np.random.rand(1, 3, 518, 518).astype("float32")})[0]
print("  实测输出", y.shape, "min/max %.2f/%.2f" % (y.min(), y.max()))
'
fi
