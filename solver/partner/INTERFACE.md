# 浏览器接口说明

浏览器操作（开网页、开局、导出素材、拖拽落子、兜底补齐）全部由 `place.py` 提供。
**主人只需要写一个 `solve(assets_dir) -> plan` 函数**，其余直接调用。

## 最快用法（三步）

```python
import place as P

def solve(assets_dir):
    # 你的算法：读 assets_dir 里的图，返回 {块序号: {"row":r, "col":c}}
    ...

rec = P.run_round(part=2, difficulty=4, solve=solve)   # 弹出窗口跑一关
print(rec["isWon"], rec["snapped"], rec["n"])
```

批量跑 12 关：

```python
P.run_all(solve, pause=5)              # 每关间隔 5 秒
P.run_all(solve, parts=(2,), diffs=(4, 9))   # 只跑指定组合
```

## `run_round()` 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `part` | 必填 | 1 / 2 / 3 |
| `difficulty` | 必填 | 4 / 9 / 16 / 25 |
| `solve` | 必填 | 你的求解器，签名 `solve(assets_dir: Path) -> dict` |
| `headless` | `False` | `False` 弹出可见浏览器窗口 |
| `outdir` | 自动 | 素材与截图目录，默认 `runs/<时间戳>_pX_dY` |
| `browser` / `page` | 无 | 传入已开的实例可复用窗口（`run_all` 内部就是这么做的） |
| `fallback` | `True` | 首次没拼完时用"剩余块塞剩余格"补齐（不读答案键） |
| `verbose` | `True` | 打印进度 |

## `run_round()` 返回

```python
{
  "tag": "p2_d4",          # 关卡标识
  "part": 2, "difficulty": 4,
  "n": 4,                  # 块数
  "theme": "white",        # white / animals / mixed
  "snapped": 4,            # 一次落子吸附成功数（= 逐块正确性判据）
  "placed": 4, "total": 4,
  "isWon": True,
  "sec": 1, "moves": 4,    # 页面自己的计时与步数
  "assets": ".../assets",  # 素材目录，方便复查
  "screenshot": "...png",
}
```

## ⚠️ 一定要开 `shuffle_names`

页面 `board.pieces` 的**数组顺序恰好等于正确位置顺序**。如果不打乱文件名，
`solve()` 直接返回 `{0:(0,0), 1:(0,1), ...}` 就能全对——**这是假的**，什么算法都没验证到。

```python
rec = P.run_round(2, 4, solve, shuffle_names=True)   # 推荐
```

实测对比（同一套恒等 plan）：

| 设置 | 结果 |
|---|---|
| `shuffle_names=False` | 4/4 通关 ← 吃泄露，假的 |
| `shuffle_names=True` | 2/4，`isWon=False` ← 真实水平 |

开启后 `export_assets` 会写出 `perm.json`（文件名 → 块标记），`run_round` 自动完成映射，
你的 `solve()` 不需要关心这件事。

## 算法成绩 vs 兜底成绩

`fallback=True` 时，首次没拼完会用"剩余块塞剩余格"补齐。返回里区分开了：

| 字段 | 含义 |
|---|---|
| `snapped` / `first_try_snapped` | **你的算法**一次吸附数，这才是要看的指标 |
| `isWon` / `placed` | 算法单独是否通关 |
| `isWon_final` / `placed_final` | 兜底之后是否通关 |

算法错了也会被兜底救回来，所以看 `snapped` 和 `isWon`，别看 `isWon_final`。

## 你的 `solve()` 契约

**输入**：`assets_dir`（`pathlib.Path`），里面有：

| 文件 | 内容 |
|---|---|
| `geom.json` | `{"rows","cols","pw","ph","boardX","boardY","theme","n"}` |
| `reference.jpg` | 参考图整图 |
| `p00.png … pNN.png` | 每块拼图（RGBA、透明背景、带凸齿/凹槽） |

**输出**（只有这一种合法格式）：

```python
{
    0: {"row": 0, "col": 0},
    1: {"row": 0, "col": 1},
    # ... 共 N 块
}
```

- 键必须是 **int**，就是文件名 `pNN` 里的 `NN`
- `row` / `col` 必须是 **int**，从 0 开始
- 必须给全 N 块，且不能两块指向同一格

格式不对会直接抛 `PlanError`，并在错误信息里说明哪里错了、应该怎么改。
例如 `{"p00": {...}}` 会报：

```
PlanError: 键必须是 int 块序号，实际是 'p00'（str）。
请返回 {0: {'row':0,'col':0}, ...}，不要用 'p00' 或 '0'
```

> 不做猜测性兼容是刻意的：静默纠正会让"算法算错"和"格式写错"混在一起，
> 出了问题很难定位。

## 单独使用的底层函数

需要更细的控制时可以直接调：

| 函数 | 作用 |
|---|---|
| `open_game(page, part, difficulty)` | 打开页面并开局，校验块数，不符自动重试 |
| `export_assets(page, outdir)` | 导出拼图块、参考图、几何信息 |
| `tag_pieces(page)` | 给每块绑定 `__tag` 作为稳定身份 |
| `place(page, plan)` | 按 `{tag: {row, col}}` 逐块拖拽，返回吸附数 |
| `state(page)` | 读 `{placed, total, isWon, moves, sec}` |
| `validate_plan(plan, n, rows, cols)` | 严格校验格式/完整性/越界/重复，不合格抛 `PlanError` |

## 已验证

| 组合 | 结果 |
|---|---|
| Part2 · 4 块 | 4/4，通关 |
| Part2 · 16 块 | 16/16，通关 |
| Part1 · 25 块 | 25/25，通关 |
| Part3 · 16 块 | 16/16，通关 |

（用外部脚本当替身求解器，验证的是"导出 → 你的 solve() → 落子"整条链路）
