# 页面机制细节（实测记录）

## 状态对象

```js
window.app                 // JigsawApp
window.app.board           // 棋盘状态
window.app.board.pieces[]  // 每块
```

piece 字段：
| 字段 | 含义 |
|---|---|
| id | `"row-col"`（正确位置） |
| x, y | 当前绘制位置（左上，含 margin 前的逻辑坐标） |
| correctX, correctY | 正确位置（**答案键，不要读**） |
| edges | `{top,right,bottom,left}`，0=直边，1=凸，-1=凹 |
| isPlaced | 是否已归位 |
| offscreenCanvas | 该块原始图像（含透明边） |
| canvasMargin | 绘制时的外扩边距 |

## 几何

`boardX + col*pieceWidth` = 该列目标 x；`boardY + row*pieceHeight` = 该行目标 y。

2×2 实测：boardX=252.06, boardY=59.92, pieceWidth=209.44, pieceHeight=157.08。

## 拖拽

```js
canvas.dispatchEvent(new MouseEvent('mousedown', {clientX, clientY, bubbles:true, buttons:1}));
// 中间若干 mousemove
canvas.dispatchEvent(new MouseEvent('mouseup', {clientX, clientY, bubbles:true, buttons:0}));
```

起点用 `piece.x + pieceWidth/2`（canvas 坐标系，加 getBoundingClientRect 偏移），
终点用目标格中心。

## 坑

- `canvasMargin` 让绘制坐标与逻辑坐标差一圈，拖拽点必须用 `piece.x`，不能用绘制像素位置
- 拼图块四周透明，YOLO 直接检测可能漏检（块内动物只占部分区域）→ 先裁 alpha 再检测
- 熊猫不在 COCO 类别里，会被识别成 `bear`；需建立别名映射
- 同类动物多块时（如两只狗）必须用 edges 形状或颜色直方图消歧
