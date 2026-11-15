# mieoemi —— 我的实现（拼图考试自动求解）

本目录是我（Hermes）写的实现，与 `solver/partner/` 完全隔离，互不覆盖。

目标页：<https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam>
三种主题（`animals` 照片 / `white` 纯白形状 / `mixed` 混合）× 四种难度（4 / 9 / 16 / 25 块）= 12 关。

---

## 一、快速开始

```bash
# 0) 环境（只做一次）
python3 -m venv yolo-env
./yolo-env/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    playwright opencv-python-headless pillow numpy
# 浏览器用系统 Chrome，不需要 playwright install chromium

# 1) 一条命令跑完 12 关（会弹出浏览器窗口，每关之间停 30 秒）
./yolo-env/bin/python auto_run.py --out ./runs/demo

# 2) 只跑关（看过程最清楚）
./yolo-env/bin/python auto_run.py --only 1 --diff 25 --out ./runs/one

# 3) 只跑单关、指定求解器
./yolo-env/bin/python auto_run.py --only 3 --diff 16 --solver hybrid_solver.py --out ./runs/one3
```

无显示器的服务器上加 `xvfb-run -a` 前缀即可；`--headless` 则完全不出窗口。

---

## 二、文件清单

### 日常使用（这几个就够）

| 文件 | 作用 |
|---|---|
| `auto_run.py` | **全自动入口**：开浏览器 → 逐关做题 → 截图 → 汇总 `RESULTS.md` |
| `browser_driver.py` | **浏览器驱动**：把「导出素材」「落子」拆成可独立调用的能力（库 or CLI） |
| `hybrid_solver.py` | **主求解器**：边齿约束 + 像素 NCC 排序（推荐，命中率最高） |
| `edge_solver.py` | 纯边齿求解器：只用 alpha 形状，无内容依赖 |
| `match_solver.py` | 纯像素模板匹配：`cv2.matchTemplate`，照片主题的备选 |

### 旧版本（保留作对照，一般不跑）

| 文件 | 状态 |
|---|---|
| `solve.py` | 第一版：YOLO 类别匹配 + 滑窗 NCC 交叉验证 |
| `yolo_ncc_solver.py` | 早期：YOLO 双端检测 + 颜色直方图消歧 |
| `slide_ncc_solver.py` | 纯 numpy 滑窗 NCC，慢（单局约 21 秒），仅用于交叉验证 |
| `grid_ncc_solver.py` | 整格 NCC，会冲突，**已废弃** |
| `export_assets.js` | 浏览器控制台手动导出脚本（已被 `browser_driver.py` 取代） |
| `auto_summary.json` / `exam_summary.json` | 历史运行数据 |
| `RESULTS.md` | 历史结果表 |

> YOLO 已不参与求解：COCO 只有 80 类，熊猫→`bear`、白格→`chair`，且拼图块是局部裁片，
> 动物主体常不在画面里，类别信息不足以定位格子。详见第七节。

---

## 三、`auto_run.py` 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--out DIR` | `runs/<时间戳>` | 输出目录 |
| `--only 1,2` | 全部 | 只跑指定 Part（1/2/3） |
| `--diff 4,9,16,25` | `4,9,16,25` | 难度（块数） |
| `--pause 30` | `30` | **每关之间等待秒数**；支持区间 `20-45`；`0` = 连跑不停 |
| `--solver X.py` | 自动 | 指定求解器（默认 hybrid → edge 回退） |
| `--headless` | 关 | 不显示浏览器窗口（服务器用） |
| `--slowmo 60` | `0` | 每步放慢毫秒数，肉眼看得更清楚 |
| `--video` | 关 | 录屏（不需要就别加） |
| `--seed N` | 随机 | 固定文件名置换种子，便于复现 |

**默认一关一关来**：每局完成后先休息（默认 30 秒）再开下一局，输出带倒计时，
`summary.json` 里 `pause_after` 记录每关实际等待秒数。

### 输出目录结构

```
runs/demo/
├── RESULTS.md          # 结果总表
├── summary.json        # 逐关原始数据（吸附数、用时、是否完成、等待秒数）
├── shots/p1_d4.png …   # 每关完成后的截图
├── assets/p1_d4/       # 该关导出的素材（p00..pNN.png / reference.jpg / geom.json / perm.json / plan*.json）
└── video/              # 仅 --video 时有
```

---

## 四、`browser_driver.py` 用法

### 当库用

```python
from browser_driver import PuzzleDriver

with PuzzleDriver(headless=False) as drv:      # headless=False 才看得见窗口
    drv.start(part=1, difficulty=16)           # 关弹窗 → 选 Part/难度 → 开新局
    info = drv.export("./assets")              # 导出素材，返回 {n, theme, geom, perm}
    # … 自己调求解器，得到 plan = {"p03": {"row":1,"col":2}, ...}
    drv.freeze_refs()                          # 固定块对象顺序
    ok = drv.place_all(plan, perm=info["perm"])# 落子，返回吸附成功块数
    print(drv.state())                         # {placed,total,isWon,sec,moves,rows,cols}
    if not drv.state()["isWon"]:
        drv.solve_by_elimination()             # 剩余块塞剩余格
```

### 命令行

```bash
python browser_driver.py export --part 1 --diff 16 --out ./assets        # 只导出
python browser_driver.py place  --part 1 --diff 16 --out ./assets \
                                --plan ./assets/plan_edges.json          # 只落子
python browser_driver.py run    --part 1 --diff 16 --out ./assets        # 导出+求解+落子
```

三个子命令都支持 `--headless` / `--slowmo` / `--video`。

### 方法一览

| 方法 | 作用 |
|---|---|
| `launch()` / `close()` | 启动 / 关闭浏览器（也支持 `with` 语法） |
| `open_page()` | 重载考试页 |
| `start(part, difficulty)` | 关胜利弹窗 → 选 Part/难度 → 开新局 |
| `close_modal()` | 关闭胜利弹窗 |
| `export(outdir, shuffle=True, seed=None)` | 导出拼图块 + 参考图 + 几何 + 置换表 |
| `freeze_refs()` | 固定 `window.__refs`，后续按下标定位块对象 |
| `drag(idx, col, row)` | 拖一块，返回 `(是否吸附, 原始结果)` |
| `place_all(plan, perm=None)` | 批量落子，返回吸附成功数 |
| `state()` | 读 `{placed,total,isWon,sec,moves,rows,cols}` |
| `empty_cells_and_unplaced()` | 查剩余空格与未放置块 |
| `solve_by_elimination()` | 剩余块塞剩余格（吸附即正确） |
| `screenshot(path)` | 截图 |

---

## 五、求解器原理

### 5.1 `hybrid_solver.py`（主）

1. **边齿编码**：从 alpha 通道判每条边 —— 凸齿 `-1` / 凹槽 `+1` / 直边 `0`
2. **约束填格**（回溯）：外缘必须直边；相邻必须互补（`左.right == -右.left`）
3. **像素排序**：每个格子按「块内容 vs 参考格内容」的 NCC 相关度降序试候选

> 纯白块内容无纹理，相关度记 0，自动退化为纯边齿求解，不会变差。

### 5.2 `edge_solver.py`

只用前两步。4×4 及以下能唯一确定布局；5×5 存在多个合法排布，命中率会掉。

### 5.3 `match_solver.py`

`cv2.matchTemplate` + 全局贪心分配防止同一格被多块争用。适合照片主题，纯白主题无效。

### 5.4 兜底：排除法

首次落子有块未吸附时，把剩余块逐个试剩余空格 —— 页面只在位置正确时吸附，
所以「试」本身就是判据，成本 O(k²)，k 通常 ≤8。

---

## 六、口径（重要）

1. **不读答案键**。`piece.id`（=正确行列）、`piece.correctX/correctY` 一律不用。
2. **警惕数组顺序泄露**。页面 `board.pieces` 数组顺序恰好等于正确位置顺序，
   按序号落子等于作弊。因此 `export()` **默认随机置换文件名**（`p00..pNN` 打乱），
   并输出 `perm.json` 记录「文件名 → 原数组下标」，落子时再还原到对象引用。
3. **只用图像驱动**。边齿来自 alpha 形状，位置来自像素相关度，均与答案字段无关。
4. **吸附数即正确性判据**。页面 `checkSnap` 只在距离足够近时才吸附，
   所以「一次吸附成功数」等于逐块正确性校验。

---

## 七、已知限制

| 限制 | 说明 |
|---|---|
| 纯白 25 块命中率约 22/25 | 白块只有 4 位齿型码，5×5 存在多个满足互补约束的合法排布。要再提升需比较**齿形弧线的连续性**（跨缝弧线是否接得上），而非只用凸/凹离散类型 |
| 对页面结构有依赖 | 依赖 `window.app.board.pieces[].offscreenCanvas` 等字段，页面改版需同步调整 `_JS_*` 片段 |
| YOLO 不可用于定位 | 见下 |

### 为什么不用 YOLO

| 拼图块内容 | COCO 预训练输出 |
|---|---|
| 熊猫 | `bear`（COCO 无 panda 类） |
| 纯白格 | `chair` / `bird`，置信度常 <0.2 |
| 绵羊 | `cow` |

更关键的是：拼图块是参考图的局部裁片，3×3 时单块仅 119×89，动物主体可能不在画面内；
即使训练出高精度模型，类别信息也无法区分「两格同种动物该放哪一格」。瓶颈在信息量，不在模型。

---

## 八、实测成绩（2026-11-15）

12 关全部完成。照片主题 25 块已做到一次吸附 25/25；纯白 25 块受方法上限影响约 22/25，
靠排除法兜底后仍能完成。

详见 `RESULTS.md` 与仓库根目录 README 的「战果」一节。

---

## 九、环境事实

| 项 | 值 |
|---|---|
| Python | venv 在 `./yolo-env`（torch / ultralytics 只在旧版 YOLO 脚本需要） |
| 浏览器 | 系统 Chrome，`channel="chrome"`；`PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/tools` |
| 录屏 | Playwright 需自带 ffmpeg；缺失时 `ensure_ffmpeg()` 会自动把系统 ffmpeg 软链过去 |
| 子进程 | 外部调用求解器必须剔除 `PYTHONPATH` / `PYTHONHOME`，否则 venv 的 PIL 会 `ImportError: _imaging` |
