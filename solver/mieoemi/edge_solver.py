#!/usr/bin/env python3
"""Part 2 / Part 3 纯白拼图求解器：从 alpha 通道推断每条边的齿型，再做约束满足求解。

齿型定义（与页面一致）：
   0 = 直边（flat，棋盘外缘）
   1 = 凸齿（tab，向外突出）
  -1 = 凹槽（blank，向内凹陷）

推理只用图像本身（alpha 形状），不读 piece.id / correctX / correctY。
输出 <assets>/plan_edges.json : {"p00": {"row":r,"col":c}}
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--assets", required=True)
ap.add_argument("--edges-json", default=None, help="可选：页面 edges 快照，仅用于交叉核对")
args = ap.parse_args()

A = Path(args.assets)
geom = json.loads((A / "geom.json").read_text())
rows, cols = int(geom["rows"]), int(geom["cols"])
pw, ph = float(geom["pw"]), float(geom["ph"])


def infer_edges(img: Image.Image):
    """从 alpha 推断四边齿型。

    拼图块画布 = 格子区域 + 四周 canvasMargin。
    若某侧在格子边界之外仍有不透明像素 -> tab (1)
    若某侧在格子边界之内出现透明缺口 -> blank (-1)
    否则 flat (0)
    """
    a = np.asarray(img.convert("RGBA"))[..., 3]
    H, W = a.shape
    opacity = a > 32

    mx0 = (W - pw) / 2.0
    my0 = (H - ph) / 2.0
    x0, x1 = int(round(mx0)), int(round(mx0 + pw))
    y0, y1 = int(round(my0)), int(round(my0 + ph))

    # 判定：
    #   格子外仍有不透明像素           -> -1 凸齿 tab
    #   边中心带出现明显透明缺口        -> +1 凹槽 blank
    #   否则                            ->  0 直边
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
            edges[side] = -1          # tab 向外
        elif center_gap(side) >= 0.40:
            edges[side] = 1           # blank 向内
        else:
            edges[side] = 0
    return edges


def solve(edges_by_piece):
    """回溯填格：外缘必须 flat，相邻齿必须互补。"""
    names = list(edges_by_piece)
    n = len(names)
    assert n == rows * cols, f"piece count {n} != {rows}x{cols}"

    def fits(name, r, c):
        e = edges_by_piece[name]
        # 棋盘外缘必须直边
        if r == 0 and e["top"] != 0: return False
        if r == rows - 1 and e["bottom"] != 0: return False
        if c == 0 and e["left"] != 0: return False
        if c == cols - 1 and e["right"] != 0: return False
        # 内部边不能是直边
        if r > 0 and e["top"] == 0: return False
        if r < rows - 1 and e["bottom"] == 0: return False
        if c > 0 and e["left"] == 0: return False
        if c < cols - 1 and e["right"] == 0: return False
        return True

    grid = [[None] * cols for _ in range(rows)]
    used = set()

    def bt(idx):
        if idx == rows * cols:
            return True
        r, c = divmod(idx, cols)
        for name in names:
            if name in used or not fits(name, r, c):
                continue
            e = edges_by_piece[name]
            ok = True
            if r > 0:
                up = edges_by_piece[grid[r - 1][c]]
                if up["bottom"] != -e["top"]: ok = False
            if c > 0:
                lf = edges_by_piece[grid[r][c - 1]]
                if lf["right"] != -e["left"]: ok = False
            if not ok:
                continue
            grid[r][c] = name
            used.add(name)
            if bt(idx + 1):
                return True
            used.discard(name)
            grid[r][c] = None
        return False

    if not bt(0):
        return None
    return {grid[r][c]: {"row": r, "col": c} for r in range(rows) for c in range(cols)}


def main():
    files = sorted(A.glob("p*.png"))
    edges_by_piece = {}
    for f in files:
        e = infer_edges(Image.open(f))
        edges_by_piece[f.stem] = e
        print(f"{f.stem}: {e}")

    # 与页面 edges 交叉核对（如果提供了快照）
    if args.edges_json:
        ref = json.loads(Path(args.edges_json).read_text())
        diff = 0
        for k, v in edges_by_piece.items():
            r = ref.get(k)
            if r and r != v:
                diff += 1
                print(f"  [edge mismatch] {k}: image={v} page={r}")
        print(f"与页面 edges 一致: {len(files)-diff}/{len(files)}")

    plan = solve(edges_by_piece)
    if plan is None:
        print("无解：齿型约束不成立")
        return
    print("\n解：")
    for k, v in plan.items():
        print(f"  {k} -> ({v['row']},{v['col']})")
    (A / "plan_edges.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    print("wrote", A / "plan_edges.json")


if __name__ == "__main__":
    main()
