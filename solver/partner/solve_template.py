"""求解器模板 —— 主人只需要填 solve() 这一个函数。

浏览器操作（开局/导出/落子/兜底）全部由 place.py 包办，这里只管"看图算位置"。

运行：
    python solve_template.py              # 只跑 Part2 的 4 块，弹窗口
    python solve_template.py --part 1 --diff 25
    python solve_template.py --all        # 12 关全跑，每关间隔 5 秒
"""
import argparse
import json
from pathlib import Path

import place as P


def solve(assets_dir: Path) -> dict:
    """读 assets_dir 里的素材，返回每块该放哪一格。

    输入（由 place.py 导出，已经放在 assets_dir 里）：
        geom.json       {"rows":2, "cols":2, "pw":223.9, "ph":167.9,
                         "boardX":282.6, "boardY":183.1, "theme":"white", "n":4}
        reference.jpg   参考图（整图）
        p00.png, p01.png, ...   每块拼图（RGBA，透明背景，带凸齿/凹槽）

    返回：
        {块序号: {"row": 行, "col": 列}}
        块序号就是文件名 pNN 里的 NN（整数）。
        键也可以写成 "p03" 或 "3"，会被自动统一。

    ──────────────────────────────────────────────────────────
    你要写的就是这个函数。下面是思路提示，不是完整实现：

    第一步：从 alpha 通道判断每条边是凸齿 / 凹槽 / 直边
            - 格子边界之外还有不透明像素 → 凸齿
            - 格子内侧边缘是透明的     → 凹槽
            - 都不是                   → 直边

    第二步：用约束填格
            - 棋盘外缘的边必须是直边
            - 相邻两块必须互补（左边块的 right 齿 == 右边块 left 齿的相反）

    第三步（可选，提升命中率）：照片主题的块有纹理，
            可以用内容相似度给候选排序，让回溯先试最像的位置。
            纯白块没有纹理，跳过这步。
    ──────────────────────────────────────────────────────────
    """
    geom = json.loads((assets_dir / "geom.json").read_text())
    rows, cols = geom["rows"], geom["cols"]

    pieces = sorted(p for p in assets_dir.glob("p*.png"))

    plan = {}
    # TODO: 换成你自己的算法
    for i, _ in enumerate(pieces):
        plan[i] = {"row": i // cols, "col": i % cols}

    return plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, default=2)
    ap.add_argument("--diff", type=int, default=4)
    ap.add_argument("--all", action="store_true", help="12 关全跑")
    ap.add_argument("--pause", type=float, default=5)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-shuffle", action="store_true",
                    help="不打乱文件名（不推荐：页面数组顺序就是答案，会得到假通过率）")
    a = ap.parse_args()

    if a.all:
        P.run_all(solve, headless=a.headless, pause=a.pause,
                  shuffle_names=not a.no_shuffle)
    else:
        rec = P.run_round(a.part, a.diff, solve, headless=a.headless,
                          shuffle_names=not a.no_shuffle)
        print(json.dumps({k: rec[k] for k in
                          ("n", "snapped", "placed", "total", "isWon", "sec")},
                         ensure_ascii=False))
