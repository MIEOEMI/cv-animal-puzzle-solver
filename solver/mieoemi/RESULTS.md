# 全难度通关记录（3 Part × 4 难度 = 12 组）

- 考试页面：https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam
- 实测时间：2026-11-15
- 结果：**12/12 完成**，其中 **12/12 一次吸附全中**（吸附只在位置正确时触发，等价逐块正确性校验）

| Part | 难度 | 块数 | 主题 | 求解器 | 一次吸附 | 页面计时 | 结果 |
|---|---|---|---|---|---|---|---|
| Part 1 · 动物照片 | 4 块 | 4 | `animals` | `edge_solver.py` | 4/4 | 2s | ✅ |
| Part 1 · 动物照片 | 9 块 | 9 | `animals` | `edge_solver.py` | 9/9 | 2s | ✅ |
| Part 1 · 动物照片 | 16 块 | 16 | `animals` | `edge_solver.py` | 16/16 | 3s | ✅ |
| Part 1 · 动物照片 | 25 块 | 25 | `animals` | `edge_solver.py` | 25/25 | 4s | ✅ |
| Part 2 · 纯白形状 | 4 块 | 4 | `white` | `edge_solver.py` | 4/4 | 2s | ✅ |
| Part 2 · 纯白形状 | 9 块 | 9 | `white` | `edge_solver.py` | 9/9 | 2s | ✅ |
| Part 2 · 纯白形状 | 16 块 | 16 | `white` | `edge_solver.py` | 16/16 | 3s | ✅ |
| Part 2 · 纯白形状 | 25 块 | 25 | `white` | `edge_solver.py` | 25/25 | 4s | ✅ |
| Part 3 · 混合 | 4 块 | 4 | `mixed` | `edge_solver.py` | 4/4 | 2s | ✅ |
| Part 3 · 混合 | 9 块 | 9 | `mixed` | `edge_solver.py` | 9/9 | 2s | ✅ |
| Part 3 · 混合 | 16 块 | 16 | `mixed` | `edge_solver.py` | 16/16 | 3s | ✅ |
| Part 3 · 混合 | 25 块 | 25 | `mixed` | `edge_solver.py` | 25/25 | 4s | ✅ |

## 求解方法

| 求解器 | 适用 | 原理 |
|---|---|---|
| `edge_solver.py` | white / mixed / animals 通吃 | 从 alpha 通道推断每边齿型（`-1` 凸齿 / `+1` 凹槽 / `0` 直边），回溯填格：外缘必须直边、相邻齿必须互补 |
| `match_solver.py` | animals（照片有纹理） | 裁格子区域 → 缩放对齐参考图 cell → `cv2.matchTemplate` 找峰值 → 全局贪心分配防冲突 |

`edge_solver` 更快更稳，12 组全部由它解出；`match_solver` 作为照片主题的备选与交叉验证。

## 三条实测坑

1. **`b.pieces` 数组顺序 == 正确位置顺序**。诊断确认 `pieces[i].correctX/Y` 恒等于第 i 格，所以"把第 i 块拖到第 i 格"就能通关——页面自带答案泄露。本仓库两个求解器**都不使用**这个性质：`edge_solver` 只读 alpha 形状，`match_solver` 只读像素。
   为排除泄露，做过**文件名随机置换测试**：把 16 块按随机置换命名为 `r00..r15` 再求解，解出的布局与真实布局一致 → 形状约束确实唯一确定了解。
2. **边齿语义与直觉相反**：页面 `-1` 是凸齿（伸出格子外），`+1` 是凹槽（咬进格子内）。按"`+1`=凸"写，与页面一致率只有 0/4。
3. **子进程继承 `PYTHONPATH` 会让 venv 的 PIL 崩掉**（`ImportError: cannot import name '_imaging'`）。外部脚本调求解器时必须剔除 `PYTHONPATH`/`PYTHONHOME`。

## 复现

```bash
# 素材目录需含 geom.json / reference.jpg / p00.png..pNN.png
python edge_solver.py  --assets <素材目录>   # 输出 plan_edges.json
python match_solver.py --assets <素材目录>   # 输出 plan.json
```

导出素材用**中性文件名**（`pNN`），不带 `piece.id`，避免文件名泄露答案。
