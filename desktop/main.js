const { app, BrowserWindow, Menu, shell, dialog } = require('electron');
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
// DATA_ROOT: nơi lưu các bản ghi JSON (users, pillar_tests, tram_tong...) —
// thư mục riêng, không ảnh hưởng gì tới cấu trúc thư mục ảnh/PDF cũ.
// FILES_ROOT: PHẢI trỏ đúng vào thư mục "List End Of Line Test" đã dùng từ
// trước tới giờ (chứa sẵn thư mục con "Charge Point") — để PDF/ảnh xuất ra
// tiếp tục lưu đúng chỗ cũ, không tạo thư mục "Charge Point" mới ở nơi khác.
const SHARED_DRIVE_NAME = 'Charge Station Documents';

let DATA_ROOT = null;
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

function checkDataRoot() {
  const sharedRoot = findSharedDriveRoot();
  if (!sharedRoot) {
    throw new Error(
      `Không tìm thấy Shared Drive "${SHARED_DRIVE_NAME}" ở ổ đĩa nào trên máy này.\n\n` +
      `Kiểm tra lại: Google Drive for Desktop đã mở và đăng nhập đúng tài khoản có quyền ` +
      `vào Shared Drive "${SHARED_DRIVE_NAME}" chưa, và đã đồng bộ xong chưa.`
    );
  }
  DATA_ROOT = path.join(sharedRoot, 'App Data');
  FILES_ROOT = path.join(sharedRoot, 'List End Of Line Test');
  fs.mkdirSync(DATA_ROOT, { recursive: true });
  fs.mkdirSync(FILES_ROOT, { recursive: true });
  appendLog(`DATA_ROOT=${DATA_ROOT} FILES_ROOT=${FILES_ROOT}`);
  startLogSync(DATA_ROOT);
}

function waitForBackend(retries = 30, delayMs = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    function check() {
      attempts += 1;
      const req = http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => {
        if (res.statusCode === 200) resolve();
        else retry();
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
  checkDataRoot();

  const exePath = getBackendExePath();
  if (!fs.existsSync(exePath)) {
    appendLog(`Không tìm thấy file backend: ${exePath}`);
    throw new Error(`Không tìm thấy file backend:\n${exePath}`);
  }

  appendLog(`Khởi động backend: ${exePath}`);
  backendProcess = spawn(exePath, [], {
    env: {
      ...process.env,
      DATA_ROOT,
      ROOT_PATH: FILES_ROOT,
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
