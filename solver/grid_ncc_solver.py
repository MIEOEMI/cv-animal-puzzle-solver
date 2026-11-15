#!/usr/bin/env python3
"""拼图匹配（纯 numpy，无 torch）：
把每块拼图的可见区域与参考图每个格子做多尺度归一化互相关，取最相似的格子。
仅使用图像内容，不读页面答案键。
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path("/home/agent/workspace/hermes-new/home/profiles/lab/cache/browser-use/workspace/20261111_014153_3d292dbe/assets")


def to_arr(im, size=None):
    if size:
        im = im.resize(size, Image.BILINEAR)
    return np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0


def crop_opaque(img):
    """裁掉拼图块的透明/白边，返回可见内容区域。"""
    a = np.asarray(img.convert("RGBA"))
    alpha = a[..., 3]
    if alpha.max() == 0:
        return img.convert("RGB")
    ys, xs = np.where(alpha > 16)
    if len(ys) == 0:
        return img.convert("RGB")
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    return img.convert("RGB").crop(box)


def ncc(a, b):
    """归一化互相关，a/b 同尺寸。"""
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 1e-9 else -1.0


def main():
    geom = json.loads((ASSETS / "geom.json").read_text())
    rows, cols = geom["rows"], geom["cols"]

    ref = Image.open(ASSETS / "reference.jpg").convert("RGB")
    W, H = ref.size
    cell_w, cell_h = W / cols, H / rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            crop = ref.crop((int(c * cell_w), int(r * cell_h),
                             int((c + 1) * cell_w), int((r + 1) * cell_h)))
            cells.append({"row": r, "col": c, "img": crop})

    results = {}
    for p in sorted(ASSETS.glob("piece_*.png")):
        piece = Image.open(p).convert("RGBA")
        piece = crop_opaque(piece)

        best = (-2.0, None)
        for cell in cells:
            # 同尺寸后算 NCC（拼图块是格子的裁剪，形状接近）
            pw, ph = piece.size
            target = cell["img"].resize((pw, ph), Image.BILINEAR)
            score = ncc(to_arr(piece), to_arr(target))
            if score > best[0]:
                best = (score, cell)
        results[p.name] = {
            "row": best[1]["row"], "col": best[1]["col"],
            "ncc": round(best[0], 4),
        }
        print(f"{p.name}: row={best[1]['row']} col={best[1]['col']} ncc={best[0]:.4f}")

    out = ASSETS / "solution_ncc.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print("\nwrote", out)

    # 一致性检查：每个格子只能用一次
    used = [(v["row"], v["col"]) for v in results.values()]
    print("格子唯一性:", "OK" if len(set(used)) == len(used) else f"冲突 {used}")


if __name__ == "__main__":
    main()
