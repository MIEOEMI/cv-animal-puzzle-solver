#!/usr/bin/env python3
"""拼图求解器 v2：YOLO 检测 + 滑窗 NCC 交叉验证，输出拖拽计划。

用法:
  python solve.py --assets <assets目录> [--geom geom.json]
输出: <assets>/plan.json  {"<piece文件>": {"row":r,"col":c,"via":...,"agree":bool}}

注意: 本脚本只读图像，不读取页面 correctX/correctY。
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("--assets", required=True)
ap.add_argument("--model", default="yolov8n.pt")
args = ap.parse_args()

A = Path(args.assets)
geom = json.loads((A / "geom.json").read_text())
model = YOLO(args.model)


def detect(img, conf=0.12):
    res = model(np.array(img.convert("RGB")), verbose=False, conf=conf)[0]
    best = None
    for b in res.boxes:
        c = res.names[int(b.cls)]
        cf = float(b.conf)
        xy = b.xyxy[0].tolist()
        area = (xy[2] - xy[0]) * (xy[3] - xy[1])
        if best is None or area > best[2]:
            best = (c, cf, area)
    return best


def sig(img, bins=6):
    a = np.array(img.convert("RGB").resize((48, 48))).reshape(-1, 3)
    h, _ = np.histogramdd(a, bins=(bins,) * 3, range=((0, 256),) * 3)
    h = h.flatten()
    s = h.sum()
    return h / s if s else h


def crop_opaque(img):
    a = np.asarray(img.convert("RGBA"))
    alpha = a[..., 3]
    if alpha.max() == 0:
        return img.convert("RGB")
    ys, xs = np.where(alpha > 32)
    pad = 2
    return img.convert("RGB").crop((
        max(0, xs.min() - pad), max(0, ys.min() - pad),
        min(a.shape[1], xs.max() + 1 + pad), min(a.shape[0], ys.max() + 1 + pad)))


def slide_ncc(ref_gray, tpl_gray, stride=3):
    rh, rw = ref_gray.shape
    th, tw = tpl_gray.shape
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


rows, cols = geom["rows"], geom["cols"]
ref_rgb = Image.open(A / "reference.jpg")
W, H = ref_rgb.size
ref_gray = np.asarray(ref_rgb.convert("L"), dtype=np.float32) / 255.0
cell_w, cell_h = W / cols, H / rows

cells = []
for r in range(rows):
    for c in range(cols):
        crop = ref_rgb.crop((int(c * cell_w), int(r * cell_h),
                             int((c + 1) * cell_w), int((r + 1) * cell_h)))
        d = detect(crop)
        cells.append({"r": int(r), "c": int(c), "cls": d[0] if d else None, "sig": sig(crop)})

plan = {}
used = set()
for p in sorted(A.glob("piece_*.png")):
    im = Image.open(p)
    d = detect(im)
    psig = sig(im)

    # 路线 A：类别匹配
    via, chosen = "color", None
    cands = [i for i, x in enumerate(cells) if x["cls"] == (d[0] if d else None) and i not in used]
    if cands:
        via = "class"
    else:
        cands = [i for i in range(len(cells)) if i not in used]
    best_i, best_s = None, -1.0
    for i in cands:
        s = float(np.dot(psig, cells[i]["sig"]) /
                  (np.linalg.norm(psig) * np.linalg.norm(cells[i]["sig"]) + 1e-12))
        if s > best_s:
            best_s, best_i = s, i

    # 路线 B：滑窗 NCC
    tpl = crop_opaque(im).convert("L").resize((int(cell_w), int(cell_h)), Image.Resampling.BILINEAR)
    tpl_arr = np.asarray(tpl, dtype=np.float32) / 255.0
    _, x, y = slide_ncc(ref_gray, tpl_arr, stride=3)
    bx = min(cols - 1, int((x + tpl.size[0] / 2) / cell_w))
    by = min(rows - 1, int((y + tpl.size[1] / 2) / cell_h))
    ncc_i = next(i for i, cc in enumerate(cells) if cc["r"] == by and cc["c"] == bx)

    agree = (best_i == ncc_i)
    final = best_i if agree else best_i  # 不一致时以类别+颜色为准，见 README
    used.add(final)
    plan[p.name] = {"row": int(cells[final]["r"]), "col": int(cells[final]["c"]),
                    "via": via, "agree": agree,
                    "ncc_cell": [by, bx]}
    print(f"{p.name}: cls={d[0] if d else None} -> ({cells[final]['r']},{cells[final]['c']}) "
          f"via={via} ncc_agree={agree}")

(A / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
print("wrote", A / "plan.json")
