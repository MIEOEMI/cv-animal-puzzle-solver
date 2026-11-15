#!/usr/bin/env python3
"""拼图考试浏览器驱动：把「导出素材」和「落子」拆成可单独调用的模块。

两种用法
--------
1) 当库用：

    from browser_driver import PuzzleDriver

    with PuzzleDriver(headless=True) as drv:
        drv.start(part=1, difficulty=16)        # 开新局
        info = drv.export("../assets")          # 导出素材（中性文件名+置换表）
        # ... 在这里调求解器，得到 plan = {"p03": {"row":1,"col":2}, ...}
        drv.freeze_refs()                       # 固定块对象顺序
        drv.place_all(plan)                     # 落子，返回吸附成功数
        print(drv.state())                      # {"placed":16,"total":16,"isWon":True,...}

2) 当命令行用：

    python browser_driver.py export --part 1 --diff 16 --out ./assets
    python browser_driver.py place  --out ./assets --plan ./assets/plan_edges.json
    python browser_driver.py run    --part 1 --diff 16      # 导出+求解+落子一条龙

约定
----
* 素材用**中性文件名** p00..pNN，并输出 perm.json（文件名 -> 原数组下标）。
  页面 board.pieces 数组顺序恰好等于正确位置顺序，直接按序号落子等于作弊；
  导出打乱后，求解器只能靠图像/形状判断。
* 落子按**对象引用**拖拽（window.__refs[i]），不读 piece.id / correctX / correctY。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import subprocess
import sys
import time
from pathlib import Path

URL = "https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam"

# ---------------------------------------------------------------- JS 片段

_JS_EXPORT = """() => {
  const b = window.app.board;
  return JSON.stringify({
    geom: {rows:b.rows, cols:b.cols, pw:b.pieceWidth, ph:b.pieceHeight,
           boardX:b.boardX, boardY:b.boardY},
    theme: window.app.currentTheme,
    pieces: b.pieces.map((p,i) => ({i, dataUrl: p.offscreenCanvas.toDataURL('image/png')})),
    ref: document.getElementById('preview-img').src
  });
}"""

_JS_START = """([part, diff]) => {
  const p = document.querySelector('input[name="exam-part"][value="'+part+'"]');
  const d = document.querySelector('input[name="exam-difficulty"][value="'+diff+'"]');
  if (p) { p.checked = true; p.dispatchEvent(new Event('change',{bubbles:true})); }
  if (d) { d.checked = true; d.dispatchEvent(new Event('change',{bubbles:true})); }
  document.getElementById('btn-exam-start').click();
  return 1;
}"""

_JS_CLOSE_MODAL = """() => {
  const m = document.getElementById('victory-modal');
  if (m && getComputedStyle(m).display !== 'none') {
    const btn = document.getElementById('btn-play-again');
    if (btn) { btn.click(); return 'closed'; }
  }
  return 'none';
}"""

_JS_FREEZE = """() => { const b = window.app.board; window.__refs = b.pieces.slice(); return window.__refs.length; }"""

_JS_DRAG = """([idx, col, row]) => {
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

_JS_STATE = """() => {
  const b = window.app.board;
  return JSON.stringify({placed: b.placedCount, total: b.totalPieces,
    isWon: window.app.isWon, sec: window.app.timer.seconds, moves: b.moveCount,
    rows: b.rows, cols: b.cols});
}"""

_JS_EMPTY = """() => {
  const b = window.app.board, empty = [];
  for (let r=0; r<b.rows; r++) for (let c=0; c<b.cols; c++)
    if (!b.pieces.some(p => p.isPlaced && p.row===r && p.col===c)) empty.push([r,c]);
  const un = [];
  window.__refs.forEach((p,i) => { if (!p.isPlaced) un.push(i); });
  return JSON.stringify({empty, un});
}"""

# 新局就绪：块数必须等于目标难度、棋盘尺寸对应、且状态已归零。
# 只判断"棋盘存在"会拿到上一关的旧棋盘（难度 9 的关导出成 4 块就是这么来的）。
_JS_READY = """(diff) => {
  const b = window.app && window.app.board;
  if (!b || !b.pieces) return false;
  const n = b.pieces.length;
  return n === diff
      && b.rows * b.cols === diff
      && (b.placedCount || 0) === 0
      && (b.moveCount || 0) === 0;
}"""


# ---------------------------------------------------------------- 录屏依赖
"""
def ensure_ffmpeg(verbose=True):
    #确保 Playwright 录屏所需的 ffmpeg 存在；缺了就软链系统 ffmpeg。

    #Playwright 要求 <PLAYWRIGHT_BROWSERS_PATH>/ffmpeg-<revision>/ffmpeg-linux，
    #但它不自带该二进制时不会自动找系统 ffmpeg。这里直接从 browsers.json 读出
    #revision，把 `which ffmpeg` 软链过去，免去 `playwright install ffmpeg` 的下载。
    #返回可用路径或 None。
    #
    import json as _json
    import os as _os
    import shutil as _shutil

    if _os.environ.get("PLAYWRIGHT_SKIP_VERIFY") == "1":
        return None
    try:
        import playwright as _pw_pkg
    except ImportError:
        return None

    base = _os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not base:
        base = str(Path(_pw_pkg.__file__).parent / "driver" / "package" / ".local-browsers")
    bjson = Path(_pw_pkg.__file__).parent / "driver" / "package" / "browsers.json"
    rev = None
    try:
        for b in _json.loads(bjson.read_text()).get("browsers", []):
            if b.get("name") == "ffmpeg":
                rev = b.get("revision")
                break
    except Exception:
        pass
    if not rev:
        return None

    target = Path(str(base)) / f"ffmpeg-{rev}" / "ffmpeg-linux"
    if target.exists():
        return str(target)
    src = _shutil.which("ffmpeg")
    if not src:
        if verbose:
            print("[warn] 录屏需要 ffmpeg，但系统里也没有；请先安装 ffmpeg")
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(src)
        if verbose:
            print(f"[info] 已软链 ffmpeg: {target} -> {src}")
        return str(target)
    except Exception as e:
        if verbose:
            print(f"[warn] 软链 ffmpeg 失败: {e}")
        return None
"""

# ---------------------------------------------------------------- 驱动类

class PuzzleDriver:
    """一个实例 = 一个浏览器页面。支持 with 语法。"""

    def __init__(self, headless=True, slowmo=0, video_dir=None, channel="chrome",
                 viewport=(1400, 900), url=URL):
        self.headless = headless
        self.slowmo = slowmo
        self.video_dir = video_dir
        self.channel = channel
        self.viewport = viewport
        self.url = url
        self._pw = None
        self._browser = None
        self._ctx = None
        self.page = None

    # -- 生命周期 --

    def __enter__(self):
        self.launch()
        return self

    def __exit__(self, *exc):
        self.close()

    def launch(self):
        from playwright.sync_api import sync_playwright
        if self.video_dir:
            ensure_ffmpeg(verbose=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            channel=self.channel, headless=self.headless, slow_mo=self.slowmo,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        kw = {"viewport": {"width": self.viewport[0], "height": self.viewport[1]}}
        if self.video_dir:
            Path(self.video_dir).mkdir(parents=True, exist_ok=True)
            kw["record_video_dir"] = str(self.video_dir)
            kw["record_video_size"] = {"width": self.viewport[0], "height": self.viewport[1]}
        self._ctx = self._browser.new_context(**kw)
        self.page = self._ctx.new_page()
        self.page.goto(self.url, wait_until="networkidle", timeout=60000)
        self.page.wait_for_function("() => window.app && typeof window.app === 'object'",
                                    timeout=30000)
        return self

    def close(self):
        try:
            if self.page and not self.page.is_closed():
                self.page.close()          # 关页面才会落盘视频
        except Exception:
            pass
        for obj, name in ((self._ctx, "close"), (self._browser, "close")):
            try:
                if obj:
                    getattr(obj, name)()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # -- 页面操作 --

    def open_page(self):
        """重新加载考试页。"""
        self.page.goto(self.url, wait_until="networkidle", timeout=60000)
        self.page.wait_for_function("() => window.app && typeof window.app === 'object'",
                                    timeout=30000)
        return self

    def close_modal(self):
        return self.page.evaluate(_JS_CLOSE_MODAL)

    def start(self, part, difficulty, timeout=25000, retries=3):
        """关闭上一局弹窗 → 选 Part/难度 → 开新局，并确认棋盘已换成该难度。

        必须校验块数：仅判断「棋盘存在」会拿到上一关的旧棋盘，
        导致难度 9 的关导出成 4 块这类错位。
        """
        last = None
        for attempt in range(retries):
            self.close_modal()
            time.sleep(0.4 + 0.3 * attempt)
            self.page.evaluate(_JS_START, [part, difficulty])
            try:
                self.page.wait_for_function(_JS_READY, arg=difficulty, timeout=timeout)
            except Exception as e:
                last = e
                continue
            time.sleep(0.4)
            st = self.state()
            if st.get("total") == difficulty:
                return st
            last = RuntimeError(f"棋盘块数 {st.get('total')} != 难度 {difficulty}")
        raise RuntimeError(f"开新局失败（Part {part} · {difficulty} 块）：{last}")

    def state(self):
        return json.loads(self.page.evaluate(_JS_STATE))

    def screenshot(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path))
        return str(path)

    # -- 导出 --

    def export(self, outdir, shuffle=True, seed=None, expect_n=None):
        """导出拼图块 + 参考图 + 几何信息。

        返回 {"n", "theme", "geom", "perm"}；perm 只在 shuffle=True 时非空。
        """
        out = Path(outdir)
        out.mkdir(parents=True, exist_ok=True)
        for f in out.iterdir():
            if f.is_file() and f.suffix in (".png", ".jpg", ".json"):
                f.unlink()

        data = json.loads(self.page.evaluate(_JS_EXPORT))
        pieces, geom = data["pieces"], data["geom"]
        n = len(pieces)
        if expect_n is not None and n != expect_n:
            raise RuntimeError(f"导出块数 {n} != 期望 {expect_n}，棋盘可能还是上一关的")

        (out / "geom.json").write_text(json.dumps(geom, indent=1))
        (out / "reference.jpg").write_bytes(
            base64.b64decode(data["ref"].split(",", 1)[1]))

        idxs = list(range(n))
        if shuffle:
            random.Random(seed if seed is not None else int(time.time() * 1000) & 0xFFFF).shuffle(idxs)
        for j, i in enumerate(idxs):
            (out / f"p{j:02d}.png").write_bytes(
                base64.b64decode(pieces[i]["dataUrl"].split(",", 1)[1]))

        perm = {f"p{j:02d}": i for j, i in enumerate(idxs)}
        (out / "perm.json").write_text(json.dumps(perm, indent=1))

        return {"n": n, "theme": data["theme"], "geom": geom, "perm": perm,
                "outdir": str(out)}

    # -- 落子 --

    def freeze_refs(self):
        """固定当前 pieces 顺序，之后用下标定位块对象。"""
        return self.page.evaluate(_JS_FREEZE)

    def drag(self, idx, col, row):
        """把 __refs[idx] 那块拖到 (row, col)。返回 True 表示吸附成功。"""
        res = self.page.evaluate(_JS_DRAG, [idx, col, row])
        return '"ok":true' in res, res

    def place_all(self, plan, perm=None, delay=0.10):
        """按 plan 落子。

        plan: {"p03": {"row":1,"col":2}, ...}
        perm: 导出时的置换表（filename -> 原数组下标）；不给则按文件名数字当索引。
        返回吸附成功块数。
        """
        self.freeze_refs()
        ok = 0
        for name, cell in sorted(plan.items()):
            key = name if name.startswith("p") else f"p{name}"
            idx = perm.get(key, int(key[1:])) if perm else int(key.lstrip("p"))
            if self.drag(idx, cell["col"], cell["row"])[0]:
                ok += 1
            time.sleep(delay)
        return ok

    def empty_cells_and_unplaced(self):
        return json.loads(self.page.evaluate(_JS_EMPTY))

    def solve_by_elimination(self, delay=0.08):
        """剩余块塞剩余格（吸附即正确）。返回最终 state。"""
        s = self.empty_cells_and_unplaced()
        done = []
        for idx in s["un"]:
            for (r, c) in s["empty"]:
                if [r, c] in done:
                    continue
                if self.drag(idx, c, r)[0]:
                    done.append([r, c])
                    break
                time.sleep(delay)
        return self.state()


# ---------------------------------------------------------------- CLI

def _run_solver(solver_path, assets):
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONNOUSERSITE"] = "1"
    subprocess.run([sys.executable, str(solver_path), "--assets", str(assets)],
                   capture_output=True, text=True, timeout=900, env=env)
    for cand in ("plan_edges.json", "plan.json"):
        fp = Path(assets) / cand
        if fp.exists():
            return json.loads(fp.read_text()), fp
    return {}, None


def main():
    ap = argparse.ArgumentParser(description="拼图考试浏览器驱动")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--headless", action="store_true")
        p.add_argument("--slowmo", type=int, default=0)
        p.add_argument("--video", metavar="DIR", default=None)

    p_exp = sub.add_parser("export", help="只导出素材")
    common(p_exp)
    p_exp.add_argument("--part", type=int, required=True)
    p_exp.add_argument("--diff", type=int, required=True)
    p_exp.add_argument("--out", required=True)
    p_exp.add_argument("--seed", type=int, default=None)
    p_exp.add_argument("--no-shuffle", action="store_true", help="不置换文件名（不推荐）")

    p_plc = sub.add_parser("place", help="只落子（需已导出的目录与 plan）")
    common(p_plc)
    p_plc.add_argument("--out", required=True, help="素材目录（含 perm.json）")
    p_plc.add_argument("--plan", required=True)
    p_plc.add_argument("--part", type=int, default=1)
    p_plc.add_argument("--diff", type=int, default=4)

    p_run = sub.add_parser("run", help="导出 + 求解 + 落子")
    common(p_run)
    p_run.add_argument("--part", type=int, required=True)
    p_run.add_argument("--diff", type=int, required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--seed", type=int, default=None)
    p_run.add_argument("--solver", default="edge_solver.py")

    a = ap.parse_args()

    if a.cmd == "export":
        with PuzzleDriver(headless=a.headless, slowmo=a.slowmo, video_dir=a.video) as drv:
            drv.start(a.part, a.diff)
            info = drv.export(a.out, shuffle=not a.no_shuffle, seed=a.seed)
            print(json.dumps({k: v for k, v in info.items() if k != "perm"},
                             ensure_ascii=False))
            print("导出完成:", info["outdir"], f"{info['n']} 块, theme={info['theme']}")

    elif a.cmd == "place":
        out = Path(a.out)
        perm = json.loads((out / "perm.json").read_text()) if (out / "perm.json").exists() else None
        plan = json.loads(Path(a.plan).read_text())
        with PuzzleDriver(headless=a.headless, slowmo=a.slowmo, video_dir=a.video) as drv:
            drv.start(a.part, a.diff)
            drv.freeze_refs()
            ok = drv.place_all(plan, perm=perm)
            print("吸附:", ok, "/", len(plan))
            st = drv.state()
            if not st["isWon"]:
                st = drv.solve_by_elimination()
                print("兜底后:", st)
            else:
                print("完成:", st)

    else:
        out = Path(a.out)
        with PuzzleDriver(headless=a.headless, slowmo=a.slowmo, video_dir=a.video) as drv:
            drv.start(a.part, a.diff)
            info = drv.export(out, seed=a.seed)
            solver = Path(__file__).parent / a.solver
            plan, plan_file = _run_solver(solver, out)
            print(f"求解: {a.solver} -> {plan_file} ({len(plan)} 块)")
            ok = drv.place_all(plan, perm=info["perm"])
            st = drv.state()
            print("吸附:", ok, "/", info["n"], "| state:", st)
            if not st["isWon"]:
                st = drv.solve_by_elimination()
                print("兜底后:", st)


if __name__ == "__main__":
    main()
