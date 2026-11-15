#!/usr/bin/env python3
"""拼图匹配（纯 numpy 滑窗）：每块拼图内容在整张参考图上滑窗搜索最佳位置，
再换算成行列。只用图像内容，不读答案键。
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path("/home/agent/workspace/hermes-new/home/profiles/lab/cache/browser-use/workspace/20261111_014153_3d292dbe/assets")


def crop_opaque(img):
    a = np.asarray(img.convert("RGBA"))
    alpha = a[..., 3]
    if alpha.max() == 0:
        return img.convert("RGB")
    ys, xs = np.where(alpha > 32)
    if len(ys) == 0:
        return img.convert("RGB")
    pad = 2
    box = (max(0, xs.min() - pad), max(0, ys.min() - pad),
           min(a.shape[1], xs.max() + 1 + pad), min(a.shape[0], ys.max() + 1 + pad))
    return img.convert("RGB").crop(box)


def slide_match(ref_gray, tpl_gray, stride=2):
    """滑窗找模板在参考图中的最佳位置（NCC），返回 (score, x, y)。"""
    rh, rw = ref_gray.shape
    th, tw = tpl_gray.shape
    if th > rh or tw > rw:
        return -1.0, 0, 0
    t = tpl_gray - tpl_gray.mean()
    tn = np.sqrt((t * t).sum()) + 1e-9
    best = (-2.0, 0, 0)
    for y in range(0, rh - th + 1, stride):
        for x in range(0, rw - tw + 1, stride):
            w = ref_gray[y:y + th, x:x + tw]
            wm = w - w.mean()
            wn = np.sqrt((wm * wm).sum()) + 1e-9
            s = float((t * wm).sum() / (tn * wn))
            if s > best[0]:
                best = (s, x, y)
    return best


def main():
    geom = json.loads((ASSETS / "geom.json").read_text())
    rows, cols = geom["rows"], geom["cols"]

    ref = Image.open(ASSETS / "reference.jpg").convert("L")
    RW, RH = ref.size
    ref_arr = np.asarray(ref, dtype=np.float32) / 255.0
    cell_w, cell_h = RW / cols, RH / rows

    results = {}
    for p in sorted(ASSETS.glob("piece_*.png")):
        piece = crop_opaque(Image.open(p))
        pw, ph = piece.size
        # 拼图块整体缩小到格子尺寸量级再匹配（块含 tab，内容区域接近格子）
        tpl = piece.convert("L").resize((int(cell_w), int(cell_h)), Image.BILINEAR)
        tpl_arr = np.asarray(tpl, dtype=np.float32) / 255.0
        score, x, y = slide_match(ref_arr, tpl_arr, stride=3)
        cx, cy = x + tpl.size[0] / 2, y + tpl.size[1] / 2
        col = min(cols - 1, int(cx / cell_w))
        row = min(rows - 1, int(cy / cell_h))
        results[p.name] = {"row": row, "col": col, "ncc": round(score, 4),
                           "px": [x, y], "size": list(tpl.size)}
        print(f"{p.name}: -> row={row} col={col} ncc={score:.4f} at ({x},{y})")

    used = [(v["row"], v["col"]) for v in results.values()]
    ok = len(set(used)) == len(used)
    print("唯一性:", "OK" if ok else f"冲突 {used}")

    out = ASSETS / "solution_slide.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
