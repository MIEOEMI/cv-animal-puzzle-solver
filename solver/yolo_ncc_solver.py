#!/usr/bin/env python3
"""YOLO 拼图求解器：识别每块拼图的动物 -> 匹配参考网格同动物 -> 输出目标行列。

不读取页面的 answer key（correctX/correctY 或 piece.id），只用图像内容。
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

ASSETS = Path("/home/agent/workspace/hermes-new/home/profiles/lab/cache/browser-use/workspace/20261111_014153_3d292dbe/assets")

# COCO 里与本题相关的类别（熊猫会被识别为 bear）
ANIMAL_ALIASES = {
    "bear": {"panda", "bear"},
    "elephant": {"elephant"},
    "dog": {"dog"},
    "zebra": {"zebra"},
    "horse": {"horse"},
    "cow": {"cow"},
    "sheep": {"sheep"},
    "giraffe": {"giraffe"},
    "cat": {"cat"},
    "bird": {"bird"},
}


def detect(model, img: Image.Image, conf=0.15):
    """返回 (类别, 置信度, bbox面积占比)。取面积最大的检测框。"""
    arr = np.array(img.convert("RGB"))
    res = model(arr, verbose=False, conf=conf)[0]
    best = None
    for box in res.boxes:
        cls = res.names[int(box.cls)]
        c = float(box.conf)
        xyxy = box.xyxy[0].tolist()
        area = (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1])
        if best is None or area > best[2]:
            best = (cls, c, area)
    return best


def color_signature(img: Image.Image, bins=8):
    """RGB 直方图，用于同类动物消歧。"""
    small = img.convert("RGB").resize((64, 64))
    arr = np.array(small).reshape(-1, 3)
    hist, _ = np.histogramdd(arr, bins=(bins, bins, bins), range=((0, 256),) * 3)
    hist = hist.flatten()
    s = hist.sum()
    return hist / s if s else hist


def main():
    geom = json.loads((ASSETS / "geom.json").read_text())
    rows, cols = geom["rows"], geom["cols"]

    model = YOLO("yolov8n.pt")

    # 1) 参考图切 cell 并检测
    ref = Image.open(ASSETS / "reference.jpg")
    W, H = ref.size
    cell_w, cell_h = W / cols, H / rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            box = (int(c * cell_w), int(r * cell_h), int((c + 1) * cell_w), int((r + 1) * cell_h))
            crop = ref.crop(box)
            det = detect(model, crop)
            cells.append({
                "row": r, "col": c,
                "cls": det[0] if det else None,
                "conf": det[1] if det else 0.0,
                "sig": color_signature(crop).tolist(),
            })
            print(f"[ref] ({r},{c}) -> {det[0] if det else 'NO DET'} conf={det[1]:.3f}" if det else f"[ref] ({r},{c}) -> NO DET")

    # 2) 每块拼图检测
    pieces = []
    for p in sorted(ASSETS.glob("piece_*.png")):
        img = Image.open(p)
        det = detect(model, img)
        pieces.append({
            "file": p.name,
            "cls": det[0] if det else None,
            "conf": det[1] if det else 0.0,
            "sig": color_signature(img).tolist(),
        })
        print(f"[piece] {p.name} -> {det[0] if det else 'NO DET'} conf={det[1]:.3f}" if det else f"[piece] {p.name} -> NO DET")

    # 3) 匹配：类别优先，同类多候选用直方图相似度
    used = set()
    mapping = {}
    for pc in pieces:
        cands = [i for i, c in enumerate(cells)
                 if c["cls"] == pc["cls"] and i not in used]
        if not cands:
            # 类别没检出/对不上，退化为全表颜色匹配
            cands = [i for i in range(len(cells)) if i not in used]
            why = "fallback-color"
        else:
            why = "class"
        best_i, best_sim = None, -1.0
        for i in cands:
            sim = float(np.dot(pc["sig"], cells[i]["sig"]) /
                        (np.linalg.norm(pc["sig"]) * np.linalg.norm(cells[i]["sig"]) + 1e-12))
            if sim > best_sim:
                best_sim, best_i = sim, i
        used.add(best_i)
        mapping[pc["file"]] = {
            "row": cells[best_i]["row"], "col": cells[best_i]["col"],
            "via": why, "sim": round(best_sim, 3),
            "piece_cls": pc["cls"], "cell_cls": cells[best_i]["cls"],
        }
        print(f"[match] {pc['file']} -> row={cells[best_i]['row']} col={cells[best_i]['col']} via={why} sim={best_sim:.3f}")

    out = ASSETS / "solution.json"
    out.write_text(json.dumps(mapping, indent=1, ensure_ascii=False))
    print("\nwrote", out)
    return mapping


if __name__ == "__main__":
    main()
