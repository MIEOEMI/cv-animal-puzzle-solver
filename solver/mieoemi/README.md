# mieoemi —— 我的实现

| 文件 | 说明 |
|---|---|
| `solve.py` | 主求解器（CLI）：YOLO 类别匹配 + 滑窗 NCC 交叉验证，输出 `plan.json` |
| `yolo_ncc_solver.py` | 早期版本：YOLO 双端检测 + 颜色直方图消歧 |
| `slide_ncc_solver.py` | 纯 numpy 滑窗 NCC（慢但稳，用于交叉验证） |
| `grid_ncc_solver.py` | 整格 NCC（会冲突，已废弃，留作对照） |
| `export_assets.js` | 浏览器控制台导出脚本：拼图块 + 参考图 + 几何 → JSON |

用法：

```bash
python solve.py --assets /path/to/assets   # 需要 assets/geom.json + piece_*.png + reference.jpg
```

实测：Part 1 · 2×2 → 4/4 块，4 步，00:49。
