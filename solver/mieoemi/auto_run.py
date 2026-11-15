#!/usr/bin/env python3
"""拼图考试全自动脚本：启动浏览器 → 逐关做题 → 截图 → 汇总。

默认行为
--------
* **弹出可见的浏览器窗口**（不加 --headless 就是有头模式）
* **一关一关来**：每局完成后休息 --pause 秒（默认 5）再开下一关
* 不录屏（需要时加 --video）

用法
----
    ./yolo-env/bin/python auto_run.py --out ./runs/demo
    ./yolo-env/bin/python auto_run.py --only 1 --diff 25 --out ./runs/one
    ./yolo-env/bin/python auto_run.py --pause 20-45 --out ./runs/demo
    ./yolo-env/bin/python auto_run.py --headless --out ./runs/demo   # 服务器无窗口

设计要点
--------
* 开新局后必须校验「块数 == 目标难度」，否则会拿到上一关的旧棋盘
  （历史 bug：难度 9 的关导出成 4 块，求解器直接拒解）。
* 导出用随机置换的中性文件名（p00..pNN），切断「数组顺序即答案」的泄露；
  落子时按 perm.json 还原到块对象引用。
* 子进程必须剔除 PYTHONPATH/PYTHONHOME，否则 venv 里的 PIL 会 ImportError。
* 吸附只在位置正确时触发，所以「一次吸附数」= 逐块正确性判据。

本脚本内所有浏览器操作都走 `browser_driver.PuzzleDriver`，
不再重复实现 start / export / drag，避免两处逻辑分叉后再踩同一个坑。
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_driver import PuzzleDriver, ensure_ffmpeg  # noqa: E402

HERE = Path(__file__).resolve().parent
PY = sys.executable
ENV = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
ENV["PYTHONNOUSERSITE"] = "1"

SOLVER_PLAN = {
    "hybrid_solver.py": "plan_hybrid.json",
    "edge_solver.py": "plan_edges.json",
    "match_solver.py": "plan.json",
}
PART_NAMES = {1: "Part 1 · 动物照片", 2: "Part 2 · 纯白形状", 3: "Part 3 · 混合"}


def parse_pause(spec):
    """'30' -> 固定 30s；'20-45' -> 区间内随机。返回 (lo, hi)。"""
    s = str(spec).strip().replace("~", "-").replace("－", "-")
    if "-" in s:
        lo, hi = (float(x) for x in s.split("-", 1))
    else:
        lo = hi = float(s)
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def wait_between(lo, hi, label=""):
    """关与关之间的等待，带倒计时输出。返回实际等待秒数。"""
    if hi <= 0:
        return 0.0
    total = random.uniform(lo, hi)
    print(f"\n⏸  本关已完成，休息 {total:.0f}s 后再开下一关"
          f"{('（' + label + '）') if label else ''}", flush=True)
    left = total
    while left > 0.05:
        tick = min(5.0, left)
        left -= tick
        print(f"   倒计时 {left:.0f}s", flush=True)
        time.sleep(tick)
    return total


def norm_plan(path):
    """把求解器输出统一成 pNN -> {row,col}。"""
    if not os.path.exists(path):
        return {}
    out = {}
    for k, v in json.load(open(path)).items():
        kk = k.replace(".png", "")
        if kk.startswith("piece_"):
            kk = "p" + kk[len("piece_"):].replace("_", "")
        out[kk] = v
    return out


def solve_assets(assets: Path, force=None):
    """跑求解器，返回 (plan_pNN, solver_name)。force 指定则只用该求解器。"""
    order = [force] if force else ["hybrid_solver.py", "edge_solver.py"]
    n_pieces = len(list(assets.glob("p*.png")))
    best, used = {}, None
    for s in order:
        if s not in SOLVER_PLAN:
            raise SystemExit(f"未知求解器: {s}（可选 {', '.join(SOLVER_PLAN)}）")
        subprocess.run([PY, str(HERE / s), "--assets", str(assets)],
                       capture_output=True, text=True, timeout=900, env=ENV)
        cand = norm_plan(assets / SOLVER_PLAN[s])
        if len(cand) > len(best):
            best, used = cand, s
        if len(best) == n_pieces:
            break
    return best, used


def run_one(drv, part, diff, root: Path, seed=None, solver=None):
    """跑一关：开新局 → 导出 → 求解 → 落子 → 兜底 → 截图。"""
    tag = f"p{part}_d{diff}"
    A = root / "assets" / tag

    drv.start(part, diff)                                # 内部校验块数
    info = drv.export(A, seed=seed, expect_n=diff)       # 再校验一次导出块数
    plan, used_solver = solve_assets(A, force=solver)
    ok = drv.place_all(plan, perm=info["perm"])
    st = drv.state()

    rec = {"tag": tag, "part": part, "difficulty": diff, "theme": info["theme"],
           "n": info["n"], "solver": used_solver, "plan_size": len(plan),
           "first_try_snapped": ok, **st}

    # 排除法兜底：剩余块 → 剩余格（吸附即正确）
    if not st["isWon"]:
        rec["after_fallback"] = drv.solve_by_elimination()

    rec["screenshot"] = drv.screenshot(root / "shots" / f"{tag}.png")
    return rec


def main():
    ap = argparse.ArgumentParser(description="拼图考试全自动（默认弹出浏览器窗口）")
    ap.add_argument("--only", default=None, help="逗号分隔 Part，如 1,2")
    ap.add_argument("--diff", default="4,9,16,25", help="难度（块数），逗号分隔")
    ap.add_argument("--out", default=None, help="输出目录（默认 runs/<时间戳>）")
    ap.add_argument("--pause", default="5",
                    help="每关之间等待秒数（默认 5）；支持区间如 3-8；0 表示连跑")
    ap.add_argument("--solver", default=None,
                    help="指定求解器（hybrid_solver.py / edge_solver.py / match_solver.py），"
                         "默认 hybrid 优先、失败退 edge")
    ap.add_argument("--headless", action="store_true", help="不显示浏览器窗口（服务器用）")
    ap.add_argument("--slowmo", type=int, default=0, help="每步放慢毫秒数，便于肉眼观察")
    ap.add_argument("--video", action="store_true", help="录屏（可选）")
    ap.add_argument("--seed", type=int, default=None, help="固定置换种子，便于复现")
    a = ap.parse_args()

    parts = [int(x) for x in (a.only.split(",") if a.only else ["1", "2", "3"])]
    diffs = [int(x) for x in a.diff.split(",")]
    combos = [(p, d) for p in parts for d in diffs]

    root = Path(a.out) if a.out else HERE / "runs" / time.strftime("%Y%m%d_%H%M%S")
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "shots").mkdir(parents=True, exist_ok=True)
    lo, hi = parse_pause(a.pause)

    if a.video:
        ensure_ffmpeg(verbose=True)

    recs = []

    def dump():
        (root / "summary.json").write_text(
            json.dumps(recs, indent=1, ensure_ascii=False))

    with PuzzleDriver(headless=a.headless, slowmo=a.slowmo,
                      video_dir=(root / "video") if a.video else None) as drv:
        print(f"页面就绪: {drv.page.title()}", flush=True)

        for i, (part, diff) in enumerate(combos):
            t0 = time.time()
            seed = (a.seed + i) if a.seed is not None else None
            rec = run_one(drv, part, diff, root, seed=seed, solver=a.solver)
            rec["wall_sec"] = round(time.time() - t0, 2)

            fin = rec.get("after_fallback", rec)
            rec["final_placed"] = fin["placed"]
            rec["final_won"] = fin["isWon"]
            recs.append(rec)
            dump()

            mark = "✅" if rec["final_won"] else "❌"
            print(f"{mark} [{i + 1}/{len(combos)}] {rec['tag']:8s} {rec['theme']:8s} "
                  f"n={rec['n']:>2} solver={rec['solver'] or '-':16s} "
                  f"吸附 {rec['first_try_snapped']}/{rec['n']} "
                  f"页面 {rec['sec']}s 总耗时 {rec['wall_sec']}s", flush=True)

            # 一关一关来：这局完成后再等一段时间，才开下一关
            if i < len(combos) - 1:
                nxt = combos[i + 1]
                rec["pause_after"] = round(
                    wait_between(lo, hi, f"下一关 {PART_NAMES[nxt[0]]} · {nxt[1]} 块"), 1)
                dump()

    # 汇总
    wins = sum(1 for r in recs if r.get("final_won"))
    perfect = sum(1 for r in recs if r["first_try_snapped"] == r["n"])
    lines = ["| Part | 难度 | 块数 | 主题 | 求解器 | 一次吸附 | 页面计时 | 结果 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(recs, key=lambda x: (x["part"], x["difficulty"])):
        lines.append(f"| {PART_NAMES[r['part']]} | {r['difficulty']} | {r['n']} "
                     f"| `{r['theme']}` | `{r['solver']}` | "
                     f"{r['first_try_snapped']}/{r['n']} | {r['sec']}s | "
                     f"{'✅' if r.get('final_won') else '❌'} |")
    table = "\n".join(lines)
    (root / "RESULTS.md").write_text(
        f"# 全自动运行结果 {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"**{wins}/{len(recs)} 完成，{perfect}/{len(recs)} 一次吸附全中**\n\n"
        f"{table}\n", encoding="utf-8")
    print("\n" + table)
    print(f"\n完成 {wins}/{len(recs)}，一次吸附全中 {perfect}/{len(recs)}")
    print(f"输出目录: {root}")


if __name__ == "__main__":
    main()
