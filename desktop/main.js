const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');

const PORT = 5678;
const APP_URL = `http://127.0.0.1:${PORT}/login.html`;

// Chặn mở nhiều app cùng lúc — nếu bấm mở app lần nữa lúc lần trước đang
// khởi động (backend chưa kịp sẵn sàng, hay xảy ra khi thấy app "đứng" rồi
// bấm mở lại), 2 tiến trình backend sẽ tranh nhau đúng 1 cổng (5678) và
// đều lỗi. Thay vào đó chỉ focus lại cửa sổ đang có.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

// Ghi log ra file LOCAL trước (nhanh), rồi định kỳ gửi nội dung đó cho
// chính backend (đã có sẵn kết nối Google Drive API) để đẩy lên Drive —
// không còn copy file trực tiếp vào ổ đĩa ánh xạ Google Drive for Desktop
// nữa (đúng kiểu thao tác từng gây lỗi Access denied/Paused không rõ
// nguyên nhân trên máy đồng nghiệp).
const LOCAL_LOG_PATH = path.join(app.getPath('userData'), 'app.log');
let logSyncTimer = null;

function appendLog(line) {
  const entry = `${new Date().toISOString()} | ${line}\n`;
  try {
    fs.mkdirSync(path.dirname(LOCAL_LOG_PATH), { recursive: true });
    // Giới hạn kích thước file log local — tránh phình to vô hạn qua nhiều lần mở app.
    if (fs.existsSync(LOCAL_LOG_PATH) && fs.statSync(LOCAL_LOG_PATH).size > 2_000_000) {
      fs.writeFileSync(LOCAL_LOG_PATH, '');
    }
    fs.appendFileSync(LOCAL_LOG_PATH, entry, 'utf8');
  } catch (_) { /* ghi log không được làm sập app chính */ }
  console.log(entry.trim());
}

// POST JSON đơn giản tới chính backend cục bộ (127.0.0.1) — dùng cho cả
// đồng bộ log và tải PDF vừa vẽ lên Drive.
function httpPostJson(url, bodyObj) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify(bodyObj), 'utf8');
    const req = http.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': body.length },
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (err) { reject(err); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function startLogSync() {
  const filename = `${os.hostname()}-electron.log`;
  const syncOnce = () => {
    let content;
    try { content = fs.readFileSync(LOCAL_LOG_PATH, 'utf8'); } catch (_) { return; }
    httpPostJson(`http://127.0.0.1:${PORT}/api/upload-electron-log.php`, { filename, content })
      .catch(() => {}); // đồng bộ log là phụ — lỗi ở đây bỏ qua
  };
  syncOnce();
  logSyncTimer = setInterval(syncOnce, 30000);
}

let backendProcess = null;
let mainWindow = null;

function getBackendExePath() {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, 'backend-dist', 'rb-control-backend')
    : path.join(__dirname, 'backend-dist', 'rb-control-backend');
  return path.join(base, 'rb-control-backend.exe');
}

// Đợi backend không chỉ "còn sống" (health 200) mà phải THẬT SỰ sẵn sàng
// (ready:true — đã tải xong tài khoản từ Drive) rồi mới mở cửa sổ. Nếu chỉ
// đợi health 200 thì cửa sổ có thể mở ra trước khi dữ liệu tải xong, người
// dùng đăng nhập ngay sẽ bị báo nhầm "sai tài khoản hoặc mật khẩu".
function waitForBackend(retries = 120, delayMs = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    function check() {
      attempts += 1;
      const req = http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => {
        let body = '';
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => {
          if (res.statusCode === 200) {
            try {
              if (JSON.parse(body).ready) { resolve(); return; }
            } catch (_) { /* body chưa parse được — coi như chưa sẵn sàng, thử lại */ }
          }
          retry();
        });
      });
      req.on('error', retry);
    }
    function retry() {
      if (attempts >= retries) { reject(new Error('Backend không khởi động được sau ' + (retries * delayMs / 1000) + 's')); return; }
      setTimeout(check, delayMs);
    }
    check();
  });
}

async function startBackend() {
  appendLog(`=== App khởi động (version ${app.getVersion()}) ===`);

  const exePath = getBackendExePath();
  if (!fs.existsSync(exePath)) {
    appendLog(`Không tìm thấy file backend: ${exePath}`);
    throw new Error(`Không tìm thấy file backend:\n${exePath}`);
  }

  // Tài khoản, dữ liệu, ảnh và PDF giờ đều qua thẳng Google Drive API (xem
  // backend/drive_store.py) — không còn cần tìm ổ đĩa Google Drive for
  // Desktop nào cả, chỉ cần máy có mạng internet.
  appendLog(`Khởi động backend: ${exePath}`);
  backendProcess = spawn(exePath, [], {
    env: { ...process.env, PORT: String(PORT) },
    windowsHide: true,
  });

  backendProcess.stdout.on('data', (d) => console.log(`[backend] ${d}`));
  backendProcess.stderr.on('data', (d) => console.error(`[backend] ${d}`));
  backendProcess.on('exit', (code) => appendLog(`Backend thoát với mã ${code}`));

  try {
    await waitForBackend();
    appendLog('Backend đã sẵn sàng (health check OK)');
  } catch (err) {
    appendLog(`Backend không sẵn sàng: ${err.message}`);
    throw err;
  }

  startLogSync();
}

// Render HTML thành PDF bằng chính Chromium có sẵn của Electron (cửa sổ ẩn,
// không hiện ra) — thay cho Playwright (tốn thêm ~700MB tải riêng 1 bộ
// Chromium khác chỉ để làm đúng việc này). Sau khi vẽ xong, gửi thẳng nội
// dung PDF cho backend để tải lên Drive — không ghi ra ổ đĩa ánh xạ nào cả.
async function renderHtmlToPdfBuffer(html) {
  const tmpHtmlPath = path.join(os.tmpdir(), `rb-control-pdf-${Date.now()}-${Math.random().toString(36).slice(2)}.html`);
  fs.writeFileSync(tmpHtmlPath, html, 'utf8');
  const hiddenWin = new BrowserWindow({ show: false, webPreferences: { offscreen: false } });
  try {
    await hiddenWin.loadFile(tmpHtmlPath);
    return await hiddenWin.webContents.printToPDF({ pageSize: 'A4', printBackground: true });
  } finally {
    hiddenWin.close();
    fs.unlink(tmpHtmlPath, () => {});
  }
}

ipcMain.handle('render-pdf', async (event, html, driveTarget) => {
  try {
    const pdfBuffer = await renderHtmlToPdfBuffer(html);
    const res = await httpPostJson(`http://127.0.0.1:${PORT}/api/upload-pdf-to-drive.php`, {
      baseFolder: driveTarget.baseFolder,
      folderPath: driveTarget.folderPath,
      filename: driveTarget.filename,
      id: driveTarget.id,
      linkColumn: driveTarget.linkColumn,
      pdfBase64: pdfBuffer.toString('base64'),
    });
    return res;
  } catch (err) {
    appendLog(`Lỗi render/tải PDF lên Drive: ${(err && err.message) || err}`);
    return { ok: false, error: String((err && err.message) || err) };
  }
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    icon: `${__dirname}/icon.ico`,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.loadURL(APP_URL);

  // Link mở tab mới (vd Xem PDF) thì mở bằng trình duyệt mặc định của máy,
  // không mở thành cửa sổ Electron mới.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// Nếu người dùng cố mở thêm 1 lần nữa lúc app đã đang chạy (vd tưởng app bị
// đứng nên bấm mở lại) — chỉ đưa cửa sổ đang có ra trước, không mở thêm gì.
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  try {
    await startBackend();
  } catch (err) {
    dialog.showErrorBox('Không khởi động được RB Control', String((err && err.message) || err));
    app.quit();
    return;
  }
  appendLog('Mở cửa sổ chính');
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function killBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  if (logSyncTimer) {
    clearInterval(logSyncTimer);
    logSyncTimer = null;
  }
}

app.on('window-all-closed', () => {
  appendLog('Đóng app (window-all-closed)');
  killBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', killBackend);
