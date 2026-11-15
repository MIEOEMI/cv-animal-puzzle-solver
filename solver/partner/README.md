# 采用mieoemi给的浏览器导出方案

## 文件

| 文件 | 作用 | 状态 |
|---|---|---|
| `place.py` | **浏览器侧**：开局、导出素材、打标记、把块拖到指定格子 | ✅ 已实测 |
| `main.py` | 早期尝试（`requests` + `BeautifulSoup` 抓图片） | ❌ 走不通，见下 |
| `yolo_detector.py` | 早期占位（加载 yolov8n） | ⏸ 未使用 |

## 为什么 main.py 走不通

拼图块和参考图都是 canvas 画的 data URL，HTML 里没有真实图片地址。
`requests.get(url)` 只拿到空壳 HTML，`soup.find('img')['src']` 取到的不是拼图数据。
必须用 Playwright 进页面内存里读（见 `place.py` 的 `READ_BOARD_JS`）。

## place.py 用法

```python
from playwright.sync_api import sync_playwright
import place

with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=False)   # False 才有窗口
    page = br.new_page(viewport={"width": 1400, "height": 900})

    place.open_game(page, part=2, difficulty=4)   # 开局并校验块数
    board = place.export_assets(page, "assets")   # 导出 p00..pNN + 参考图 + geom
    place.tag_pieces(page)                        # 给每块打稳定标记

    plan = {0: {"row": 0, "col": 0}, 1: {"row": 0, "col": 1},
            2: {"row": 1, "col": 0}, 3: {"row": 1, "col": 1}}
    print(place.place(page, plan))                # 返回吸附成功块数
    print(place.state(page))
```

## 对外接口

| 函数 | 作用 |
|---|---|
| `open_game(page, part, difficulty)` | 打开考试页并开局，校验块数，不符自动重试 |
| `export_assets(page, outdir)` | 导出拼图块、参考图、几何信息 |
| `tag_pieces(page)` | 给每块绑定 `__tag`，作为跨重排的稳定身份 |
| `place(page, plan)` | 按 `{tag: {row, col}}` 逐块拖拽，返回吸附数 |
| `state(page)` | 读 `{placed, total, isWon, moves, sec}` |

## 实测（2026-11-15）

`plan` 先用页面给的 `correctX/correctY` 生成（**仅用于验证 place 机制**，不是解题方案）：

| 组合 | 结果 |
|---|---|
| Part2 · 4 块 | 4/4 吸附，通关 |
| Part2 · 9 块 | 9/9 吸附，通关 |
| Part2 · 16 块 | 16/16 吸附，通关 |
| Part1 · 9 块 | 9/9 吸附，通关 |
| Part3 · 16 块 | 16/16 吸附，通关 |

## 三个坑（都已修在代码里）

1. **JS 对象的键是字符串**：从页面拿回的 `plan` 键是 `"0"`，而 `p.__tag` 是数字，
   `0 === "0"` 为假 → 一块都抓不到。`place()` 里统一转 `int`。
2. **数组会在拖拽后重排**：被拖的块提到数组末尾，用下标当身份会错位 → 用 `__tag`。
3. **块会互相重叠**：直接拖可能抓到压在上面的另一块。
   `BRING_TO_TOP_JS` 先把目标块移到数组末尾（画在最上层）再拖。

## 还没做的

求解器（从图像算出 `plan`）。目前 `plan` 只能靠 `correctX/correctY`，
真正解题要自己实现形状/内容匹配。

---

## 待修的三个问题（review 2026-11-15）

见 `brower_use_own.py`：

1. `export_assets` 里 `page.locator("#exam-reference").screenshot(...)` —— **该选择器不存在**（实测 `count=0`），会直接抛错。
   正确做法：参考图用 `document.getElementById('preview-img').src`（data URL，原始 800×600），
   而不是截图——`#preview-img` 在页面上只显示 330×600，截图会失真。
2. `open_and_start` 用递归重试，没有次数上限，极端情况会无限递归。建议改成 `for` 循环 + 最多 3 次。
3. `place(page, plan)` 还是空的 `...` —— 已提供可用的 `place.py`，直接 `from place import place` 即可，
   或把 `place.py` 里 `place()` 的函数体抄进去。
