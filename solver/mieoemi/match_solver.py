#!/usr/bin/env python3
"""拼图求解器 v3：cv2 模板匹配（主）+ YOLO 类别（辅/验证）。

原理：每块 offscreenCanvas = 拼图块图像（格子 + 四周 tab 外扩 canvasMargin），
所以 [margin : margin+pieceW, margin : margin+pieceH] 正好是参考图该格子的内容。
把它缩放到参考图 cell 尺寸，用 cv2.matchTemplate 在整张参考图上找峰值位置，
即可得到该块所属的行列。

用法:
  python match_solver.py --assets <assets目录> [--model yolov8n.pt]
输出:
  <assets>/plan.json  {"piece_xxx.png": {"row":r,"col":c,"score":0.98,...}}
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--assets", required=True)
args = ap.parse_args()

A = Path(args.assets)
geom = json.loads((A / "geom.json").read_text())
rows, cols = int(geom["rows"]), int(geom["cols"])
pw, ph = float(geom["pw"]), float(geom["ph"])

ref = cv2.imread(str(A / "reference.jpg"), cv2.IMREAD_GRAYSCALE)
RH, RW = ref.shape
cell_w, cell_h = RW / cols, RH / rows


def piece_cell(img: Image.Image):
    """从拼图块图中裁出正好等于格子的区域（去掉 tab 外扩）。"""
    W, H = img.size
    margin_x = max(0.0, (W - pw) / 2)
    margin_y = max(0.0, (H - ph) / 2)
    box = (int(round(margin_x)), int(round(margin_y)),
           int(round(margin_x + pw)), int(round(margin_y + ph)))
    box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
    return img.convert("RGB").crop(box)


def match(piece_img):
    """返回 (score, row, col, px, py)。"""
    cell = piece_cell(piece_img)
    g = cv2.cvtColor(np.array(cell), cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, (int(round(cell_w)), int(round(cell_h))), interpolation=cv2.INTER_AREA)
    res = cv2.matchTemplate(ref, g, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    cx = maxloc[0] + cell_w / 2
    cy = maxloc[1] + cell_h / 2
    col = int(min(cols - 1, max(0, np.floor(cx / cell_w))))
    row = int(min(rows - 1, max(0, np.floor(cy / cell_h))))
    return float(maxv), row, col, int(maxloc[0]), int(maxloc[1])


def main():
    files = sorted(list(A.glob("piece_*.png")) + list(A.glob("p[0-9][0-9].png")))
    results = {}
    print(f"{rows}x{cols}: {len(files)} pieces, cell {cell_w:.0f}x{cell_h:.0f}")

    # 贪心分配：全局按分数从高到低占用格子，避免冲突
    all_matches = []
    for p in files:
        score, r, c, px, py = match(Image.open(p))
        all_matches.append((score, p.name, r, c, px, py))
        print(f"  {p.name}: best=({r},{c}) score={score:.4f} at ({px},{py})")

    all_matches.sort(key=lambda x: -x[0])
    used = set()
    plan = {}
    for score, name, r, c, px, py in all_matches:
        if (r, c) in used:
            # 冲突：在同一块拼图的候选里找下一个未占用的格子
            img = Image.open(A / name)
            cell = piece_cell(img)
            g = cv2.cvtColor(np.array(cell), cv2.COLOR_RGB2GRAY)
            g = cv2.resize(g, (int(round(cell_w)), int(round(cell_h))), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(ref, g, cv2.TM_CCOEFF_NORMED)
            flat = res.copy()
            for rr in range(rows):
                for cc in range(cols):
                    if (rr, cc) in used:
                        y0 = int(rr * cell_h); x0 = int(cc * cell_w)
                        flat[y0:y0 + int(cell_h), x0:x0 + int(cell_w)] = -1
            _, maxv, _, maxloc = cv2.minMaxLoc(flat)
            cx = maxloc[0] + cell_w / 2; cy = maxloc[1] + cell_h / 2
            c2 = int(min(cols - 1, max(0, np.floor(cx / cell_w))))
            r2 = int(min(rows - 1, max(0, np.floor(cy / cell_h))))
            score = float(maxv); r, c = r2, c2
        used.add((r, c))
        plan[name] = {"row": r, "col": c, "score": round(score, 4)}
        print(f"[final] {name} -> ({r},{c}) score={score:.4f}")

    (A / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    print("wrote", A / "plan.json")
    print("占位完整:", "OK" if len(used) == rows * cols else f"{len(used)}/{rows*cols}")


if __name__ == "__main__":
    main()
