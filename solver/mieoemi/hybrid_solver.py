#!/usr/bin/env python3
"""混合求解器：边齿约束 + 像素分数排序（edge_solver 的增强版）。

动机
----
纯边齿约束在 25 块时**不唯一**——存在多个同样满足「外缘直边 + 相邻互补」的合法排布，
回溯按文件顺序取第一个解，命中率只有 17~23/25。
本版在回溯时用「块内容 vs 参考格内容」的 NCC 相关度给候选排序，
先试像素最像的位置，从而把一次命中率拉上来。

对纯白块（内容无纹理）NCC 基本恒定，等价退化为边齿求解，不会变差。

用法:
    python hybrid_solver.py --assets <目录> [--edges-json <页面 edges 快照>]
输出:
    <目录>/plan_hybrid.json
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# ---------------------------------------------------------------- 边齿推断

def infer_edges(img: Image.Image, pw: float, ph: float):
    """从 alpha 推断四边齿型。

    -1 = 凸齿（伸出格子外）
    +1 = 凹槽（咬进格子内）
     0 = 直边
    """
    a = np.asarray(img.convert("RGBA"))[..., 3]
    H, W = a.shape
    opacity = a > 32

    x0 = int(round((W - pw) / 2)); x1 = int(round(x0 + pw))
    y0 = int(round((H - ph) / 2)); y1 = int(round(y0 + ph))

    def out_count(side):
        if side == "top":
            return int(opacity[:max(0, y0 - 3), :].sum())
        if side == "bottom":
            return int(opacity[min(H, y1 + 3):, :].sum())
        if side == "left":
            return int(opacity[:, :max(0, x0 - 3)].sum())
        return int(opacity[:, min(W, x1 + 3):].sum())

    cxm, cym = (x0 + x1) // 2, (y0 + y1) // 2
    half, vhalf = int(pw * 0.18), int(ph * 0.18)

    def center_gap(side):
        if side == "top":
            seg = ~opacity[y0:y0 + 10, cxm - half:cxm + half]
        elif side == "bottom":
            seg = ~opacity[y1 - 10:y1, cxm - half:cxm + half]
        elif side == "left":
            seg = ~opacity[cym - vhalf:cym + vhalf, x0:x0 + 10]
        else:
            seg = ~opacity[cym - vhalf:cym + vhalf, x1 - 10:x1]
        return float(seg.mean()) if seg.size else 0.0

    edges = {}
    for side in ("top", "right", "bottom", "left"):
        if out_count(side) > 100:
            edges[side] = -1
        elif center_gap(side) >= 0.40:
            edges[side] = 1
        else:
            edges[side] = 0
    return edges


def piece_content(img: Image.Image, pw: float, ph: float, cell_w: int, cell_h: int):
    """取出格子区域并缩放到参考 cell 尺寸（灰度）。"""
    W, H = img.size
    x0 = int(round((W - pw) / 2)); y0 = int(round((H - ph) / 2))
    box = (max(0, x0), max(0, y0), min(W, x0 + int(pw)), min(H, y0 + int(ph)))
    g = cv2.cvtColor(np.array(img.convert("RGB").crop(box)), cv2.COLOR_RGB2GRAY)
    return cv2.resize(g, (cell_w, cell_h), interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", required=True)
    ap.add_argument("--edges-json", default=None)
    args = ap.parse_args()

    A = Path(args.assets)
    geom = json.loads((A / "geom.json").read_text())
    rows, cols = int(geom["rows"]), int(geom["cols"])
    pw, ph = float(geom["pw"]), float(geom["ph"])

    ref = cv2.imread(str(A / "reference.jpg"), cv2.IMREAD_GRAYSCALE)
    RH, RW = ref.shape
    cell_w, cell_h = RW // cols, RH // rows

    files = sorted(list(A.glob("p[0-9][0-9].png")) + list(A.glob("piece_*.png")))
    if not files:
        print("未找到拼图块 pNN.png / piece_*.png")
        return

    names, edges_by, scores = [], {}, {}
    for f in files:
        img = Image.open(f)
        names.append(f.stem)
        edges_by[f.stem] = infer_edges(img, pw, ph)
        content = piece_content(img, pw, ph, cell_w, cell_h)
        # 与参考图逐格 NCC；格子方差过小（纯白）时该格记 0，靠边齿决定
        sc = np.zeros((rows, cols), dtype=np.float32)
        for r in range(rows):
            for c in range(cols):
                patch = ref[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                if patch.shape != content.shape:
                    continue
                if patch.std() < 6 or content.std() < 6:
                    sc[r, c] = 0.0            # 无纹理：不给像素证据
                    continue
                a = patch.astype(np.float32) - patch.mean()
                b = content.astype(np.float32) - content.mean()
                d = float(np.linalg.norm(a) * np.linalg.norm(b))
                sc[r, c] = float((a * b).sum() / d) if d > 1e-6 else 0.0
        scores[f.stem] = sc
        print(f"{f.stem}: edges={edges_by[f.stem]}  best_cell="
              f"{tuple(int(v) for v in np.unravel_index(sc.argmax(), sc.shape))} "
              f"score={sc.max():.3f}")

    if args.edges_json:
        page = json.loads(Path(args.edges_json).read_text())
        diff = sum(1 for k, v in edges_by.items() if page.get(k) and page[k] != v)
        print(f"与页面 edges 一致: {len(files)-diff}/{len(files)}")

    # ---------------------------------------------------------------- 回溯

    def fits(name, r, c):
        e = edges_by[name]
        if r == 0 and e["top"] != 0: return False
        if r == rows - 1 and e["bottom"] != 0: return False
        if c == 0 and e["left"] != 0: return False
        if c == cols - 1 and e["right"] != 0: return False
        if r > 0 and e["top"] == 0: return False
        if r < rows - 1 and e["bottom"] == 0: return False
        if c > 0 and e["left"] == 0: return False
        if c < cols - 1 and e["right"] == 0: return False
        return True

    grid = [[None] * cols for _ in range(rows)]
    used = set()
    nodes = [0]

    def candidates(r, c):
        """按像素分数降序返回该格可行块。"""
        cand = [n for n in names if n not in used and fits(n, r, c)]
        cand.sort(key=lambda n: -scores[n][r, c])
        return cand

    def bt(idx):
        nodes[0] += 1
        if nodes[0] > 400000:
            return False
        if idx == rows * cols:
            return True
        r, c = divmod(idx, cols)
        for name in candidates(r, c):
            e = edges_by[name]
            if r > 0 and edges_by[grid[r - 1][c]]["bottom"] != -e["top"]:
                continue
            if c > 0 and edges_by[grid[r][c - 1]]["right"] != -e["left"]:
                continue
            grid[r][c] = name
            used.add(name)
            if bt(idx + 1):
                return True
            used.discard(name)
            grid[r][c] = None
        return False

    if not bt(0):
        print("无解：边齿约束不成立")
        return

    plan = {grid[r][c]: {"row": r, "col": c} for r in range(rows) for c in range(cols)}
    hits = sum(1 for n, v in plan.items()
               if tuple(int(x) for x in np.unravel_index(scores[n].argmax(),
                                                          scores[n].shape)) == (v["row"], v["col"]))
    print(f"\n解（搜索节点 {nodes[0]}，像素最优与最终落位一致 {hits}/{len(names)}）：")
    for k, v in plan.items():
        print(f"  {k} -> ({v['row']},{v['col']})  score={scores[k][v['row'], v['col']]:.3f}")
    (A / "plan_hybrid.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    print("wrote", A / "plan_hybrid.json")


if __name__ == "__main__":
    main()
