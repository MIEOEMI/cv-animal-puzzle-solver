# CV Animal Puzzle Solver

RoboMaster 队内 CV 练习：自动解 `cv-animal-puzzle` 拼图。

## 目标

页面 `mode=exam` 分三部分：
- **Part 1 · Animal Photos** —— 核心方法 YOLO：识别每块拼图里的动物，匹配到参考网格中同动物位置
- **Part 2 · Pure White Shapes** —— 核心方法 OpenCV：纯轮廓/直边/凹凸齿匹配
- **Part 3 · Mixed** —— 两者结合

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

## 分工

两人各写一份，`solver/` 下按作者命名，互不覆盖。
