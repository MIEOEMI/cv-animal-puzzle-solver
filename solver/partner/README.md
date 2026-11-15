# partner —— 你的实现

这里放你自己的脚本，与 `solver/hermes/` 完全隔离，互不覆盖。

约定：
- 文件名按你的习惯起，不要改 `hermes/` 下的文件
- 共用素材导出可以复用 `hermes/export_assets.js`（或自己写一份放这里）
- 有结论/踩坑记到 `notes/` 下，文件名带前缀避免冲突，例如 `notes/<你的名字>-*.md`

素材导出（可直接复用）：

```js
// 浏览器控制台
const b = window.app.board;
const out = b.pieces.map(p => ({id:p.id, edges:p.edges, dataUrl:p.offscreenCanvas.toDataURL('image/png')}));
out.push({id:'reference', dataUrl: document.getElementById('preview-img').src});
// 自行落盘
```
