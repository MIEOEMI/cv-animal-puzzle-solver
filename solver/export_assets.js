// 浏览器控制台导出脚本：把每块拼图与参考图导成 base64，供本地求解器使用
// 用法：在拼图页面控制台粘贴执行，会下载 solution 需要的图片
(function exportAssets() {
  const b = window.app.board;
  const out = [];
  b.pieces.forEach(p => {
    out.push({id: p.id, edges: p.edges, dataUrl: p.offscreenCanvas.toDataURL('image/png')});
  });
  out.push({id: 'reference', dataUrl: document.getElementById('preview-img').src});
  const blob = new Blob([JSON.stringify(out)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'puzzle_assets.json';
  a.click();
})();
