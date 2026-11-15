"""浏览器侧：把拼图块拖到指定格子。

只做一件事 —— 给一个 plan（哪块 -> 哪格），把块拖过去。
不含任何识别/求解逻辑。

用法
----
    from place import open_game, export_assets, tag_pieces, place, state

    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=False)
        page = br.new_page(viewport={"width": 1400, "height": 900})

        open_game(page, part=2, difficulty=4)      # 开一局（会校验块数）
        board = export_assets(page, "assets")      # 导出图片（可选）
        tag_pieces(page)                           # 给每块打稳定标记

        plan = {0: {"row": 0, "col": 0}, 1: {"row": 0, "col": 1},
                2: {"row": 1, "col": 0}, 3: {"row": 1, "col": 1}}
        print(place(page, plan))                   # 返回吸附成功块数
        print(state(page))
"""
import base64
import json
import time
from pathlib import Path

URL = "https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam"


# ------------------------------------------------------------------ JS 片段
# 说明：拼图块画在 canvas 里，HTML 中没有 <img>，所以只能进页面内存里取数据。
# 下面的 JS 都只是"读数据"或"调顺序"，没有任何识别逻辑。

READ_BOARD_JS = """() => {
  const b = window.app.board;
  return {
    rows: b.rows, cols: b.cols,
    pw: b.pieceWidth, ph: b.pieceHeight,
    bx: b.boardX, by: b.boardY,
    n: b.pieces.length,
    theme: window.app.currentTheme,
    pieces: b.pieces.map(p => p.offscreenCanvas.toDataURL('image/png')),
    ref: document.getElementById('preview-img').src
  };
}"""

# 画布在页面里的位置 + 缩放比 + 棋盘几何
BOARD_GEO_JS = """() => {
  const cv = document.getElementById('puzzle-canvas');
  const r = cv.getBoundingClientRect();
  const b = window.app.board;
  return {
    left: r.left, top: r.top,
    kx: cv.width / r.width, kb_y: cv.height / r.height,
    bx: b.boardX, by: b.boardY,
    pw: b.pieceWidth, ph: b.pieceHeight,
    rows: b.rows, cols: b.cols, n: b.pieces.length,
    placed: b.placedCount, total: b.totalPieces
  };
}"""

# 给每块打上稳定标记。注意：拖拽后数组顺序会变（被拖的块被提到末尾），
# 直接用下标当身份会错位，所以绑定一个 __tag。
TAG_JS = """() => {
  const b = window.app.board;
  b.pieces.forEach((p, i) => { p.__tag = i; });
  return b.pieces.length;
}"""

# 把指定标记的块提到数组末尾（= 画在最上层），避免被别的块压住抓错。
# 只调整顺序，不改位置。
BRING_TO_TOP_JS = """(tag) => {
  const b = window.app.board;
  const i = b.pieces.findIndex(p => p.__tag === tag);
  if (i < 0) return null;
  const p = b.pieces.splice(i, 1)[0];
  b.pieces.push(p);
  return {x: p.x, y: p.y, isPlaced: !!p.isPlaced};
}"""

STATE_JS = """() => {
  const b = window.app.board;
  return {placed: b.placedCount, total: b.totalPieces,
          isWon: window.app.isWon, moves: b.moveCount,
          sec: window.app.timer.seconds};
}"""

# 新局就绪判定：块数必须等于目标难度，且状态归零。
# 只判断"棋盘存在"会拿到上一关的旧棋盘（难度 9 的关会导出成 4 块）。
READY_JS = """(diff) => {
  const b = window.app && window.app.board;
  if (!b || !b.pieces) return false;
  return b.pieces.length === diff
      && b.rows * b.cols === diff
      && (b.placedCount || 0) === 0
      && (b.moveCount || 0) === 0;
}"""


# ------------------------------------------------------------------ 页面操作

def open_game(page, part, difficulty, timeout=25000, retries=3):
    """打开考试页并开一局。会校验块数，不符就重开。"""
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_function("() => window.app && typeof window.app === 'object'",
                           timeout=30000)

    for attempt in range(retries):
        page.locator(f'input[name="exam-part"][value="{part}"]').check()
        page.locator(f'input[name="exam-difficulty"][value="{difficulty}"]').check()
        page.locator("#btn-exam-start").click()
        try:
            page.wait_for_function(READY_JS, arg=difficulty, timeout=timeout)
            time.sleep(0.3)
            return state(page)
        except Exception:
            # 上一局的胜利弹窗可能挡住按钮，点一下 Play Another Puzzle 再试
            try:
                page.locator("#btn-play-again").click(timeout=2000)
            except Exception:
                pass
            time.sleep(0.5 + 0.4 * attempt)
    raise RuntimeError(f"开新局失败：Part {part} · {difficulty} 块")


def export_assets(page, outdir, shuffle_names=False):
    """导出拼图块 + 参考图 + 几何到磁盘。返回 board 字典。"""
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    board = page.evaluate(READ_BOARD_JS)

    (out / "geom.json").write_text(json.dumps({
        "rows": board["rows"], "cols": board["cols"],
        "pw": board["pw"], "ph": board["ph"],
        "boardX": board["bx"], "boardY": board["by"],
        "theme": board["theme"], "n": board["n"],
    }, indent=1))

    (out / "reference.jpg").write_bytes(
        base64.b64decode(board["ref"].split(",", 1)[1]))

    for i, data_url in enumerate(board["pieces"]):
        raw = data_url.split(",", 1)[1]          # 去掉 "data:image/png;base64,"
        name = f"p{i:02d}.png" if not shuffle_names else f"p{_shuffled(i, board['n']):02d}.png"
        (out / name).write_bytes(base64.b64decode(raw))

    return board


def _shuffled(i, n, seed=12345):
    """可选：把文件名打乱，避免"文件序号 == 位置顺序"泄露答案。"""
    import random
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order[i]


def tag_pieces(page):
    """给每块打稳定标记，之后用它来指认拼图块。"""
    return page.evaluate(TAG_JS)


def state(page):
    return page.evaluate(STATE_JS)


# ------------------------------------------------------------------ 核心：place

def place(page, plan, delay=0.12, retry=1):
    """把拼图块拖到指定格子。

    参数
    ----
    plan : {tag: {"row": r, "col": c}}
        tag 是 tag_pieces() 打上的标记（= 导出时的数组下标）。
    delay : 每块之间的间隔秒数，太急可能丢事件。
    retry : 单块失败后重试次数。

    返回
    ----
    吸附成功的块数（页面只在位置正确时吸附，所以这个数字就是正确性判据）。
    """
    geo = page.evaluate(BOARD_GEO_JS)

    # 像素坐标 -> 屏幕坐标：piece.x 是 canvas 像素，CSS 显示尺寸略有缩放
    def to_screen(canvas_x, canvas_y):
        return (geo["left"] + canvas_x / geo["kx"],
                geo["top"] + canvas_y / geo["kb_y"])

    snapped = 0
    for raw_tag, cell in plan.items():
        # ⚠️ JS 对象的键永远是字符串，从页面拿回来的 plan 键是 "0"/"1"，
        #    而 p.__tag 是数字。不转成 int 就会 0 === "0" 恒为假，一块都抓不到。
        tag = int(raw_tag) if str(raw_tag).lstrip("-").isdigit() else raw_tag
        for attempt in range(retry + 1):
            # 1) 把这块提到最上层，拿到它当前位置（避免被别的块压住抓错）
            info = page.evaluate(BRING_TO_TOP_JS, tag)
            if info is None:
                break                        # 找不到这块，跳过
            if info["isPlaced"]:
                break                        # 已经放好了

            # 2) 目标位置：格子中心
            target_cx = geo["bx"] + cell["col"] * geo["pw"] + geo["pw"] / 2
            target_cy = geo["by"] + cell["row"] * geo["ph"] + geo["ph"] / 2

            # 3) 起点：块的中心
            start_cx = info["x"] + geo["pw"] / 2
            start_cy = info["y"] + geo["ph"] / 2

            sx, sy = to_screen(start_cx, start_cy)
            tx, ty = to_screen(target_cx, target_cy)

            # 4) 真实鼠标拖拽：按下 -> 分步移动 -> 松开
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(tx, ty, steps=10)   # steps 必须 >1，否则不触发拖拽
            page.mouse.up()
            time.sleep(delay)

            # 5) 检查这块是否吸附成功（不能看下标，数组已经重排过）
            ok = page.evaluate("""(tag) => {
              const p = window.app.board.pieces.find(x => x.__tag === tag);
              return !!p && !!p.isPlaced;
            }""", tag)
            if ok:
                snapped += 1
                break
        else:
            print(f"  [warn] tag={tag} 放到 ({cell['row']},{cell['col']}) 未吸附")

    return snapped


# ------------------------------------------------------------------ 自测
if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=False, args=["--no-sandbox"])
        page = br.new_page(viewport={"width": 1400, "height": 900})

        print("开局:", open_game(page, part=2, difficulty=4))   # Part2 纯白 4 块
        board = export_assets(page, "assets")
        print(f"导出: {board['n']} 块, {board['rows']}x{board['cols']}, 主题={board['theme']}")

        tag_pieces(page)

        # ⚠️ 下面这个 plan 是"读答案"拼出来的，仅用于验证 place 机制本身，
        #    真正解题时应该由你自己的算法算出来。
        truth = page.evaluate("""() => {
          const b = window.app.board, out = {};
          b.pieces.forEach(p => {
            const col = Math.round((p.correctX - b.boardX) / b.pieceWidth);
            const row = Math.round((p.correctY - b.boardY) / b.pieceHeight);
            out[p.__tag] = {row, col};
          });
          return out;
        }""")

        print("吸附:", place(page, truth), "/", board["n"])
        print("状态:", state(page))

        input("按回车关闭浏览器...")
        br.close()
