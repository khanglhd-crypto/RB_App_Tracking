const { app, BrowserWindow, Menu, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');

const PORT = 5678;
const APP_URL = `http://127.0.0.1:${PORT}/login.html`;

// Thư mục Shared Drive dùng làm nơi lưu dữ liệu chung (đồng bộ qua Google
// Drive for Desktop) — ĐỔI lại 2 dòng này nếu máy nào gắn ổ Shared Drive
// khác chữ cái (không phải G:) hoặc tên thư mục khác.
const DATA_ROOT = 'G:\\Shared drives\\Charge Station Documents\\App Data';
const FILES_ROOT = 'G:\\Shared drives\\Charge Station Documents\\App Data\\files';

let backendProcess = null;
let mainWindow = null;

function getBackendExePath() {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, 'backend-dist', 'rb-control-backend')
    : path.join(__dirname, 'backend-dist', 'rb-control-backend');
  return path.join(base, 'rb-control-backend.exe');
}

function checkDataRoot() {
  const parent = path.dirname(DATA_ROOT);
  if (!fs.existsSync(parent)) {
    throw new Error(
      `Không tìm thấy thư mục Shared Drive:\n${parent}\n\n` +
      `Kiểm tra lại: Google Drive for Desktop đã mở chưa, và ổ đĩa Shared Drive ` +
      `có đúng chữ cái/tên như cấu hình trong app không.`
    );
  }
  fs.mkdirSync(DATA_ROOT, { recursive: true });
  fs.mkdirSync(FILES_ROOT, { recursive: true });
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
  checkDataRoot();

  const exePath = getBackendExePath();
  if (!fs.existsSync(exePath)) {
    throw new Error(`Không tìm thấy file backend:\n${exePath}`);
  }

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

  await waitForBackend();
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
}

app.on('window-all-closed', () => {
  killBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', killBackend);
