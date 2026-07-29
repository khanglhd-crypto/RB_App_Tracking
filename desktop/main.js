const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const { spawn } = require('child_process');

const PORT = 5678;
const APP_URL = `http://127.0.0.1:${PORT}/login.html`;

// Ghi log ra file LOCAL trước (nhanh, không phụ thuộc Shared Drive), rồi định
// kỳ copy file đó lên Shared Drive (_logs/<tên máy>-electron.log) để người
// quản trị đọc lại được từ máy khác khi cần chẩn đoán lỗi — không cần đồng
// nghiệp hiểu hay làm gì cả.
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

function startLogSync(dataRoot) {
  const remoteDir = path.join(dataRoot, '_logs');
  const remotePath = path.join(remoteDir, `${os.hostname()}-electron.log`);
  const syncOnce = () => {
    try {
      fs.mkdirSync(remoteDir, { recursive: true });
      fs.copyFileSync(LOCAL_LOG_PATH, remotePath);
    } catch (_) { /* đồng bộ log là phụ — lỗi ở đây bỏ qua */ }
  };
  syncOnce();
  logSyncTimer = setInterval(syncOnce, 30000);
}

// Google Drive for Desktop gắn "Shared drives" vào một ổ đĩa riêng trên MỖI
// MÁY — chữ cái ổ đĩa KHÔNG cố định giống nhau giữa các máy (tùy máy đó đã
// dùng hết ổ nào). Vì vậy KHÔNG hardcode chữ ổ đĩa — tự dò qua tất cả các ổ
// đang có trên máy, tìm ổ nào chứa đúng thư mục Shared Drive tên
// "Charge Station Documents" thì dùng ổ đó.
//
// FILES_ROOT: PHẢI trỏ đúng vào thư mục "List End Of Line Test" đã dùng từ
// trước tới giờ (chứa sẵn thư mục con "Charge Point") — để PDF/ảnh xuất ra
// tiếp tục lưu đúng chỗ cũ. Riêng dữ liệu (tài khoản, phiếu test...) giờ
// KHÔNG còn qua ổ đĩa ánh xạ này nữa — backend tự gọi thẳng Google Drive API
// (xem backend/drive_store.py), không cần "App Data" cục bộ nữa.
const SHARED_DRIVE_NAME = 'Charge Station Documents';

let FILES_ROOT = null;

let backendProcess = null;
let mainWindow = null;

function getBackendExePath() {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, 'backend-dist', 'rb-control-backend')
    : path.join(__dirname, 'backend-dist', 'rb-control-backend');
  return path.join(base, 'rb-control-backend.exe');
}

// Dò qua các ổ đĩa C: tới Z: (bỏ qua A/B — ổ đĩa mềm cũ), tìm ổ nào có
// "<ổ>:\Shared drives\Charge Station Documents" thì trả về đường dẫn đó.
function findSharedDriveRoot() {
  for (let code = 'C'.charCodeAt(0); code <= 'Z'.charCodeAt(0); code++) {
    const letter = String.fromCharCode(code);
    const candidate = `${letter}:\\Shared drives\\${SHARED_DRIVE_NAME}`;
    if (fs.existsSync(candidate)) {
      appendLog(`Tìm thấy Shared Drive ở ổ ${letter}: -> ${candidate}`);
      return candidate;
    }
  }
  appendLog(`Không tìm thấy Shared Drive "${SHARED_DRIVE_NAME}" ở ổ đĩa nào (đã quét C: đến Z:)`);
  return null;
}

function checkFilesRoot() {
  const sharedRoot = findSharedDriveRoot();
  if (!sharedRoot) {
    throw new Error(
      `Không tìm thấy Shared Drive "${SHARED_DRIVE_NAME}" ở ổ đĩa nào trên máy này.\n\n` +
      `Kiểm tra lại: Google Drive for Desktop đã mở và đăng nhập đúng tài khoản có quyền ` +
      `vào Shared Drive "${SHARED_DRIVE_NAME}" chưa, và đã đồng bộ xong chưa.\n\n` +
      `(Chỉ ảnh hưởng phần lưu ảnh/PDF — tài khoản và dữ liệu khác vẫn hoạt động qua mạng.)`
    );
  }
  FILES_ROOT = path.join(sharedRoot, 'List End Of Line Test');
  fs.mkdirSync(FILES_ROOT, { recursive: true });
  appendLog(`FILES_ROOT=${FILES_ROOT}`);
  startLogSync(path.join(sharedRoot, 'App Data'));
}

// Đợi backend không chỉ "còn sống" (health 200) mà phải THẬT SỰ sẵn sàng
// (ready:true — đã tải xong tài khoản từ Drive) rồi mới mở cửa sổ. Nếu chỉ
// đợi health 200 thì cửa sổ có thể mở ra trước khi dữ liệu tải xong, người
// dùng đăng nhập ngay sẽ bị báo nhầm "sai tài khoản hoặc mật khẩu".
function waitForBackend(retries = 60, delayMs = 500) {
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

  // Tài khoản/dữ liệu giờ qua thẳng Google Drive API (không cần ổ đĩa ánh xạ
  // nào), CHỈ ảnh/PDF mới cần Shared Drive gắn đúng ổ đĩa — nên nếu không
  // tìm thấy, chỉ cảnh báo rồi vẫn mở app bình thường (đăng nhập, xem dữ
  // liệu... vẫn dùng được), không chặn hẳn cả app như trước nữa.
  try {
    checkFilesRoot();
  } catch (err) {
    appendLog(`Cảnh báo: ${err.message}`);
    dialog.showErrorBox('Không tìm thấy thư mục lưu ảnh/PDF', err.message);
  }

  const exePath = getBackendExePath();
  if (!fs.existsSync(exePath)) {
    appendLog(`Không tìm thấy file backend: ${exePath}`);
    throw new Error(`Không tìm thấy file backend:\n${exePath}`);
  }

  appendLog(`Khởi động backend: ${exePath}`);
  backendProcess = spawn(exePath, [], {
    env: {
      ...process.env,
      ROOT_PATH: FILES_ROOT || '',
      PORT: String(PORT),
    },
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
}

// Render HTML thành PDF bằng chính Chromium có sẵn của Electron (cửa sổ ẩn,
// không hiện ra) — thay cho Playwright (tốn thêm ~700MB tải riêng 1 bộ
// Chromium khác chỉ để làm đúng việc này).
async function renderHtmlToPdf(html, pdfPath) {
  const tmpHtmlPath = path.join(os.tmpdir(), `rb-control-pdf-${Date.now()}-${Math.random().toString(36).slice(2)}.html`);
  fs.writeFileSync(tmpHtmlPath, html, 'utf8');
  const hiddenWin = new BrowserWindow({ show: false, webPreferences: { offscreen: false } });
  try {
    await hiddenWin.loadFile(tmpHtmlPath);
    const pdfBuffer = await hiddenWin.webContents.printToPDF({ pageSize: 'A4', printBackground: true });
    fs.mkdirSync(path.dirname(pdfPath), { recursive: true });
    fs.writeFileSync(pdfPath, pdfBuffer);
  } finally {
    hiddenWin.close();
    fs.unlink(tmpHtmlPath, () => {});
  }
}

ipcMain.handle('render-pdf', async (event, html, pdfPath) => {
  try {
    await renderHtmlToPdf(html, pdfPath);
    return { ok: true };
  } catch (err) {
    appendLog(`Lỗi render PDF (${pdfPath}): ${(err && err.message) || err}`);
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
