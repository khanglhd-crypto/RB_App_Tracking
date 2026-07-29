const { contextBridge, ipcRenderer } = require('electron');

// Cầu nối an toàn giữa trang web (frontend) và tiến trình chính Electron —
// dùng để nhờ Electron tự render HTML thành PDF (qua Chromium có sẵn của
// chính Electron), thay vì phải tải kèm riêng 1 bộ Chromium khác (Playwright)
// chỉ để làm việc này, giúp app nhẹ đi rất nhiều.
contextBridge.exposeInMainWorld('electronAPI', {
  renderPdf: (html, pdfPath) => ipcRenderer.invoke('render-pdf', html, pdfPath),
});
