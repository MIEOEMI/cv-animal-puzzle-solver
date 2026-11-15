# CV Animal Puzzle Solver

RoboMaster 队内 CV 练习：自动解 `cv-animal-puzzle` 拼图。

## 目标

页面 `mode=exam` 分三部分：
- **Part 1 · Animal Photos** —— 核心方法 YOLO：识别每块拼图里的动物，匹配到参考网格中同动物位置
- **Part 2 · Pure White Shapes** —— 核心方法 OpenCV：纯轮廓/直边/凹凸齿匹配
- **Part 3 · Mixed** —— 两者结合

## 战果

3 Part × 4 难度 = **12/12 全部通关**，每块一次吸附到位，单局 2–4 秒。
明细见 [`solver/mieoemi/RESULTS.md`](solver/mieoemi/RESULTS.md)。

## 目录分工（两人分开写，互不覆盖）

```
solver/mieoemi/    我的实现
solver/<你的目录>/ 你的实现（名称你定）
notes/            公共笔记，文件名带前缀防冲突
assets/           导出素材（不入库）
```

## 结构

```
solver/   求解脚本（每人一份，文件名带作者标记）
notes/    页面机制笔记、踩坑记录
assets/   导出的拼图块与参考图（不入库）
```

## 页面机制（实测，2026-11）

- `#puzzle-canvas` 923×434，`window.app` 是 `JigsawApp` 实例
- 核心状态 `app.board`：`rows/cols/totalPieces/pieces/boardX/boardY/pieceWidth/pieceHeight/placedCount`
- 每块 `piece`：`{id,row,col,x,y,correctX,correctY,edges,isPlaced,offscreenCanvas,canvasMargin}`
- 拖拽事件：`mousedown` → `mousemove` → `mouseup`（canvas 上，无 pointer 事件）
- 吸附：`checkSnap` 距离阈值 `max(26, pieceWidth*0.28)`
- 渲染：`drawImage(offscreenCanvas, x-canvasMargin, y-canvasMargin)`
- 参考图：`#preview-img`，800×600
- 启动：`input[name=exam-part]` / `input[name=exam-difficulty]` → `#btn-exam-start`

> ⚠️ 页面数据结构里直接暴露了 `correctX/correctY` 与 `id=row-col`。
> 读它就能秒解，但那等于作弊，评估的是视觉方法本身。本仓库统一走**图像识别**路线。

## 已实现思路

1. 从 `piece.offscreenCanvas.toDataURL()` 导出每块原图，`#preview-img` 导出参考图
2. 参考图按 `rows×cols` 切 cell
3. 双端检测/匹配，得到 `piece -> (row,col)`
4. 按棋盘几何计算目标坐标：`boardX + col*pieceWidth`，`boardY + row*pieceHeight`
5. 模拟 `mousedown/mousemove/mouseup` 完成拖拽

## 两条技术路线（并行验证）

- **A. YOLO**（题目要求）：`yolov8n` 检测动物类别 → 按类别匹配参考 cell
- **B. 纯 numpy 滑窗 NCC**（兜底/交叉验证）：拼图块在参考图上滑窗找最相似位置

两条路线结果一致时再执行落子。

## 环境

```bash
python3 -m venv yolo-env
./yolo-env/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
./yolo-env/bin/pip install --no-deps ultralytics
./yolo-env/bin/pip install pillow pyyaml requests scipy opencv-python-headless
```

国内网络：`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`；
torch CPU wheel 直连 `download.pytorch.org` 可用（约 167MB）。



## 实测记录（2026-11-13，Part 1 · 2×2）

| 项 | 结果 |
|---|---|
| 完成 | 4/4，4 步，49 秒（含环境摸索时间，不含安装） |
| YOLO 检测 | elephant 0.85 / dog 0.81 可靠；sheep→cow、白格→chair、熊猫→bear 有误判 |
| 滑窗 NCC | 4/4 正确，唯一性 OK，纯 Python 约 21 秒（需向量化提速） |
| 结论 | 2×2 下两条路线一致；类别匹配必须配颜色兜底 |


1. **COCO 覆盖面不足**：熊猫→`bear`、纯白格→`chair`/`bird`，置信度常低于 0.2。
   纯类别匹配会失败，必须用颜色直方图 + 滑窗 NCC 交叉验证。
2. **拼图块带透明边**：直接检测会把整块（含白底）当输入，需先按 alpha 裁出可见区域。
3. **滑窗 NCC 慢**：纯 Python 双重循环 O(n²)，800×600 参考图上 21 秒。
   提速方向：`cv2.matchTemplate`（TM_CCOEFF_NORMED）或 FFT 互相关，可到毫秒级。
4. **不要读答案键**：`piece.correctX/correctY` 与 `piece.id` 直接暴露正确位置。
   纯形状推理（`edge_solver`）与纯像素匹配（`match_solver`）均已验证可行。

## 全自动（一人一键）

```bash
# 一条命令跑完 3 Part × 4 难度，可选录屏
./yolo-env/bin/python solver/mieoemi/auto_run.py --headless --video --slowmo 80 --out ./runs/demo
```

结果落在 `--out` 目录：`shots/*.png` 每局截图、`video/*.webm` 全程录屏、`RESULTS.md` 总表、`summary.json` 原始数据。

> 录屏需要 ffmpeg。若 Playwright 自带的 ffmpeg 缺失，把系统 ffmpeg 软链过去即可：
> `ln -sf $(which ffmpeg) /opt/hermes/tools/ffmpeg-1013/ffmpeg-linux`

## 浏览器驱动（可单独调用）

`solver/mieoemi/browser_driver.py` 把**导出素材**和**落子**拆成独立能力，既能 import 也能命令行调：

```python
from browser_driver import PuzzleDriver

with PuzzleDriver(headless=True) as drv:
    drv.start(part=1, difficulty=16)     # 开新局
    info = drv.export("./assets")        # 导出（中性文件名 + perm.json 置换表）
    # ... 自己调求解器，得到 plan = {"p03": {"row":1,"col":2}, ...}
    drv.freeze_refs()                    # 固定块对象顺序
    drv.place_all(plan, perm=info["perm"])   # 落子，返回吸附数
    print(drv.state())                   # {placed, total, isWon, sec, moves, rows, cols}
    if not drv.state()["isWon"]:
        drv.solve_by_elimination()       # 剩余块塞剩余格
```

命令行三种模式：

```bash
python browser_driver.py export --part 1 --diff 16 --out ./assets        # 只导出
python browser_driver.py place  --part 1 --diff 16 --out ./assets --plan ./assets/plan_edges.json  # 只落子
python browser_driver.py run    --part 1 --diff 16 --out ./assets        # 一条龙
```

| 方法 | 作用 |
|---|---|
| `start(part, difficulty)` | 关弹窗 → 选 Part/难度 → 开新局 |
| `export(outdir, shuffle=True, seed=None)` | 导出 `p00..pNN.png` + `reference.jpg` + `geom.json` + `perm.json` |
| `freeze_refs()` | 固定 `window.__refs`，后续按下标定位块对象 |
| `drag(idx, col, row)` | 拖一块，返回 `(是否吸附, 原始结果)` |
| `place_all(plan, perm)` | 批量落子，返回吸附成功数 |
| `state()` | 读 `{placed,total,isWon,sec,moves,rows,cols}` |
| `solve_by_elimination()` | 剩余块塞剩余格（吸附即正确） |
| `screenshot(path)` | 截图 |
| `close_modal()` / `open_page()` | 关胜利弹窗 / 重载页面 |
