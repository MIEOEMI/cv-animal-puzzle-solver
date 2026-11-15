from playwright.sync_api import sync_playwright
import base64, json, pathlib

URL = "https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam"
READ_BOARD_JS = """() => {
  const b = window.app.board;
  return {
    rows: b.rows, cols: b.cols,
    pw: b.pieceWidth, ph: b.pieceHeight,
    bx: b.boardX, by: b.boardY,
    n: b.pieces.length,
    pieces: b.pieces.map(p => p.offscreenCanvas.toDataURL('image/png'))
  };
}"""

def open_and_start(page, part, difficulty):
    page.goto(URL, wait_until="networkidle")  #打开网页
    page.wait_for_function("() => window.app && typeof window.app === 'object'") #等待网页加载完成
    page.locator(f'input[name="exam-part"][value="{part}"]').check()#选择考试部分
    page.locator(f'input[name="exam-difficulty"][value="{difficulty}"]').check()#选择考试难度
    page.locator("#btn-exam-start").click()
    page.wait_for_timeout(1200)
    if page.evaluate("() => window.app.board.pieces.length") != difficulty:
        open_and_start(page, part, difficulty)
    

def export_assets(page, outdir):
    board = page.evaluate(READ_BOARD_JS)
    
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for i, data_url in enumerate(board["pieces"]):
        header, encoded = data_url.split(",", 1)
        (out / f"p{i:02d}.png").write_bytes(base64.b64decode(encoded))   #解码并保存到out下的p{i:02d}.png文件

    reference = page.locator("#exam-reference").screenshot(path=str(out / "reference.jpg"))
    (out / "geom.json").write_text(json.dumps({
        "rows": board["rows"], "cols": board["cols"],
        "pw": board["pw"], "ph": board["ph"],
        "bx": board["bx"], "by": board["by"],
        "n": board["n"],
    }, indent=2))   
    return board

def place(page, plan):
    # ← 你要写：从末尾挑块 + mouse.move/down/move/up
    
    ...

with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=False)  # False 才看得见窗口
    page = br.new_page(viewport={"width": 1400, "height": 900})
    open_and_start(page, part=2, difficulty=4)
    board = export_assets(page, "assets")
    print(board["n"], board["rows"], board["cols"])
    br.close()