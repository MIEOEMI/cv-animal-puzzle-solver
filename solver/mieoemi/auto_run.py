#!/usr/bin/env python3
"""拼图考试全自动脚本：启动浏览器 → 打开考试页 → 跑完 3 Part × 4 难度 → 记录结果。

用法:
    ./yolo-env/bin/python auto_run.py                 # 有头模式，能看到浏览器操作
    ./yolo-env/bin/python auto_run.py --headless       # 无头
    ./yolo-env/bin/python auto_run.py --only 1 --diff 4,9   # 只跑指定组合

设计要点:
  * 导出的拼图块用**随机置换**的中性文件名（p00..pNN），不让文件序号对应数组下标。
    页面 board.pieces 数组顺序恰好等于正确位置顺序，直接按序落子等于作弊；
    本脚本只让求解器读 alpha 形状，落子时再按置换表还原到对象引用。
  * 子进程必须剔除 PYTHONPATH/PYTHONHOME，否则 venv 里的 PIL 会 ImportError。
  * 吸附只在位置正确时触发，因此"一次吸附数"即逐块正确性判据。
"""
import argparse
import base64
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam"
HERE = Path(__file__).resolve().parent
PY = sys.executable
ENV = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
ENV["PYTHONNOUSERSITE"] = "1"

EXPORT_JS = """() => {
  const b = window.app.board;
  return JSON.stringify({
    geom: {rows:b.rows, cols:b.cols, pw:b.pieceWidth, ph:b.pieceHeight,
           boardX:b.boardX, boardY:b.boardY},
    theme: window.app.currentTheme,
    pieces: b.pieces.map((p,i) => ({i, dataUrl: p.offscreenCanvas.toDataURL('image/png')})),
    ref: document.getElementById('preview-img').src
  });
}"""

START_JS = """([part, diff]) => {
  const p = document.querySelector('input[name="exam-part"][value="'+part+'"]');
  const d = document.querySelector('input[name="exam-difficulty"][value="'+diff+'"]');
  if (p) { p.checked = true; p.dispatchEvent(new Event('change',{bubbles:true})); }
  if (d) { d.checked = true; d.dispatchEvent(new Event('change',{bubbles:true})); }
  document.getElementById('btn-exam-start').click();
  return 1;
}"""

CLOSE_MODAL_JS = """() => {
  const m = document.getElementById('victory-modal');
  if (m && getComputedStyle(m).display !== 'none') {
    const btn = document.getElementById('btn-play-again');
    if (btn) { btn.click(); return 'closed'; }
  }
  return 'none';
}"""

# 按 __refs[i] 的引用拖拽（不依赖 id / correctX）
DRAG_JS = """([idx, col, row]) => {
  const b = window.app.board, cv = document.getElementById('puzzle-canvas');
  const p = window.__refs[idx];
  if (!p || p.isPlaced) return JSON.stringify({skip:true});
  const rc = cv.getBoundingClientRect();
  const sx = rc.left + p.x + b.pieceWidth/2, sy = rc.top + p.y + b.pieceHeight/2;
  const tx = rc.left + b.boardX + col*b.pieceWidth + b.pieceWidth/2;
  const ty = rc.top  + b.boardY + row*b.pieceHeight + b.pieceHeight/2;
  const mk = (t,x,y) => new MouseEvent(t, {clientX:x, clientY:y, bubbles:true,
    cancelable:true, button:0, buttons: t==='mouseup'?0:1});
  cv.dispatchEvent(mk('mousedown', sx, sy));
  for (let i=1; i<=7; i++)
    cv.dispatchEvent(mk('mousemove', sx+(tx-sx)*i/7, sy+(ty-sy)*i/7));
  cv.dispatchEvent(mk('mouseup', tx, ty));
  return JSON.stringify({ok: p.isPlaced, placed: b.placedCount});
}"""

FREEZE_REFS_JS = """() => { const b = window.app.board; window.__refs = b.pieces.slice(); return window.__refs.length; }"""

STATE_JS = """() => {
  const b = window.app.board;
  return JSON.stringify({placed: b.placedCount, total: b.totalPieces,
    isWon: window.app.isWon, sec: window.app.timer.seconds, moves: b.moveCount});
}"""

EMPTY_JS = """() => {
  const b = window.app.board, empty = [];
  for (let r=0; r<b.rows; r++) for (let c=0; c<b.cols; c++)
    if (!b.pieces.some(p => p.isPlaced && p.row===r && p.col===c)) empty.push([r,c]);
  const un = [];
  window.__refs.forEach((p,i) => { if (!p.isPlaced) un.push(i); });
  return JSON.stringify({empty, un});
}"""


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


def solve_assets(assets: Path, theme: str):
    """跑求解器，返回 (plan_pNN, solver_name)。white/mixed 先边齿，photo 先模板匹配。"""
    order = (["edge_solver.py", "match_solver.py"] if theme != "photo"
             else ["match_solver.py", "edge_solver.py"])
    best, used = {}, None
    for s in order:
        subprocess.run([PY, str(HERE / s), "--assets", str(assets)],
                       capture_output=True, text=True, timeout=900, env=ENV)
        pj = "plan.json" if "match" in s else "plan_edges.json"
        cand = norm_plan(assets / pj)
        if len(cand) > len(best):
            best, used = cand, s
        if len(best) == len(list(assets.glob("p*.png"))):
            break
    return best, used


def run_one(page, part, diff, outdir: Path, shots: Path, seed=None):
    tag = f"p{part}_d{diff}"
    A = outdir / tag
    if A.exists():
        shutil.rmtree(A)
    A.mkdir(parents=True)

    page.evaluate(CLOSE_MODAL_JS)
    time.sleep(0.5)
    page.evaluate(START_JS, [part, diff])
    page.wait_for_function("() => window.app && window.app.board && window.app.board.pieces.length > 0",
                           timeout=20000)
    time.sleep(0.6)

    data = json.loads(page.evaluate(EXPORT_JS))
    theme, pieces = data["theme"], data["pieces"]
    n = len(pieces)
    json.dump(data["geom"], open(A / "geom.json", "w"), indent=1)
    open(A / "reference.jpg", "wb").write(base64.b64decode(data["ref"].split(",", 1)[1]))

    # 随机置换：文件名 pNN 的内容来自数组下标 perm[NN]，切断"序号=位置"
    idxs = list(range(n))
    random.Random(seed if seed is not None else hash(tag) & 0xFFFF).shuffle(idxs)
    perm = {f"p{j:02d}": i for j, i in enumerate(idxs)}
    for j, i in enumerate(idxs):
        open(A / f"p{j:02d}.png", "wb").write(
            base64.b64decode(pieces[i]["dataUrl"].split(",", 1)[1]))
    json.dump({k: v for k, v in perm.items()}, open(A / "perm.json", "w"), indent=1)

    plan, solver = solve_assets(A, theme)

    page.evaluate(FREEZE_REFS_JS)
    ok = 0
    for name, cell in sorted(plan.items()):
        if not (name.startswith("p") and name[1:].isdigit()):
            continue
        arr_idx = perm.get(name)
        if arr_idx is None:
            continue
        res = page.evaluate(DRAG_JS, [arr_idx, cell["col"], cell["row"]])
        if '"ok":true' in res:
            ok += 1
        time.sleep(0.10)

    st = json.loads(page.evaluate(STATE_JS))
    rec = {"tag": tag, "part": part, "difficulty": diff, "theme": theme, "n": n,
           "solver": solver, "plan_size": len(plan), "first_try_snapped": ok, **st}

    # 排除法兜底：剩余块 → 剩余格（吸附即正确）
    if not st["isWon"]:
        s2 = json.loads(page.evaluate(EMPTY_JS))
        done = []
        for idx in s2["un"]:
            for (r, c) in s2["empty"]:
                if [r, c] in done:
                    continue
                if '"ok":true' in page.evaluate(DRAG_JS, [idx, c, r]):
                    done.append([r, c])
                    break
                time.sleep(0.08)
        rec["after_fallback"] = json.loads(page.evaluate(STATE_JS))

    shot = shots / f"{tag}.png"
    page.screenshot(path=str(shot))
    rec["screenshot"] = str(shot)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--only", default=None, help="逗号分隔 Part，如 1,2")
    ap.add_argument("--diff", default="4,9,16,25")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--video", action="store_true", help="录屏（WebM），便于回看浏览器操作过程")
    ap.add_argument("--slowmo", type=int, default=0, help="每步放慢毫秒数，便于肉眼观察")
    a = ap.parse_args()

    parts = [int(x) for x in (a.only.split(",") if a.only else ["1", "2", "3"])]
    diffs = [int(x) for x in a.diff.split(",")]

    root = Path(a.out) if a.out else HERE / "runs" / time.strftime("%Y%m%d_%H%M%S")
    outdir, shots = root / "assets", root / "shots"
    (outdir).mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=a.headless, slow_mo=a.slowmo,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx_kw = {"viewport": {"width": 1400, "height": 900}}
        if a.video:
            vdir = root / "video"
            vdir.mkdir(parents=True, exist_ok=True)
            ctx_kw["record_video_dir"] = str(vdir)
            ctx_kw["record_video_size"] = {"width": 1400, "height": 900}
        ctx = browser.new_context(**ctx_kw)
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_function("() => window.app && typeof window.app === 'object'", timeout=30000)
        print(f"页面就绪: {page.title()}")

        recs = []
        for part in parts:
            for diff in diffs:
                t0 = time.time()
                rec = run_one(page, part, diff, outdir, shots, seed=a.seed)
                rec["wall_sec"] = round(time.time() - t0, 2)
                # 最终状态以兜底后为准
                fin = rec.get("after_fallback", rec)
                rec["final_placed"] = fin["placed"]
                rec["final_won"] = fin["isWon"]
                recs.append(rec)
                (root / "summary.json").write_text(
                    json.dumps(recs, indent=1, ensure_ascii=False))
                mark = "✅" if rec["final_won"] else "❌"
                print(f"{mark} {rec['tag']:8s} {rec['theme']:8s} n={rec['n']:>2} "
                      f"solver={rec['solver'] or '-':16s} "
                      f"吸附 {rec['first_try_snapped']}/{rec['n']} "
                      f"页面 {rec['sec']}s 总耗时 {rec['wall_sec']}s")

        # 总表
        wins = sum(1 for r in recs if r.get("final_won"))
        perfect = sum(1 for r in recs if r["first_try_snapped"] == r["n"])
        lines = ["| Part | 难度 | 块数 | 主题 | 求解器 | 一次吸附 | 页面计时 | 结果 |",
                 "|---|---|---|---|---|---|---|---|"]
        names = {1: "Part 1 · 动物照片", 2: "Part 2 · 纯白形状", 3: "Part 3 · 混合"}
        for r in sorted(recs, key=lambda x: (x["part"], x["difficulty"])):
            lines.append(f"| {names[r['part']]} | {r['difficulty']} | {r['n']} | `{r['theme']}` "
                         f"| `{r['solver']}` | {r['first_try_snapped']}/{r['n']} "
                         f"| {r['sec']}s | {'✅' if r.get('final_won') else '❌'} |")
        table = "\n".join(lines)
        (root / "RESULTS.md").write_text(
            f"# 全自动运行结果 {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"**{wins}/{len(recs)} 完成，{perfect}/{len(recs)} 一次吸附全中**\n\n{table}\n",
            encoding="utf-8")
        print("\n" + table)
        print(f"\n完成 {wins}/{len(recs)}，一次吸附全中 {perfect}/{len(recs)}")
        print(f"输出目录: {root}")
        if a.video:
            page.close()          # 关闭页面才会落盘视频
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
