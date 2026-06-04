/**
 * VOXScript - Electron 메인 프로세스
 * 앱 시작 시 FastAPI 백엔드를 백그라운드로 띄우고 React UI를 창으로 표시
 */

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const API_PORT = 8765;
const DEV_MODE = process.env.NODE_ENV === "development";

let mainWindow = null;
let backendProcess = null;

// ── 백엔드 시작 ──────────────────────────────────────────
function startBackend() {
  const backendDir = path.join(__dirname, "..", "backend");

  // 패키징 시: 동봉된 Python 인터프리터 사용
  // 개발 시: 시스템 Python (venv 권장)
  const pythonCmd = app.isPackaged
    ? path.join(process.resourcesPath, "python", "python.exe")
    : "python";

  const scriptPath = path.join(backendDir, "main.py");

  console.log(`[Electron] 백엔드 시작: ${pythonCmd} ${scriptPath}`);

  backendProcess = spawn(pythonCmd, [scriptPath], {
    cwd: backendDir,
    env: { ...process.env, VOXSCRIPT_PORT: String(API_PORT) },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.on("data", (data) => {
    console.log(`[Backend] ${data.toString().trim()}`);
  });
  backendProcess.stderr.on("data", (data) => {
    console.error(`[Backend ERR] ${data.toString().trim()}`);
  });
  backendProcess.on("exit", (code) => {
    console.log(`[Backend] 종료됨 (code: ${code})`);
  });
}

// ── 백엔드 준비 대기 ─────────────────────────────────────
function waitForBackend(retries = 20, interval = 500) {
  return new Promise((resolve, reject) => {
    const check = (remaining) => {
      if (remaining <= 0) {
        reject(new Error("백엔드 시작 시간 초과"));
        return;
      }
      const req = http.get(`http://127.0.0.1:${API_PORT}/`, (res) => {
        if (res.statusCode === 200) resolve();
        else check(remaining - 1);
      });
      req.on("error", () => setTimeout(() => check(remaining - 1), interval));
      req.end();
    };
    check(retries);
  });
}

// ── 메인 창 생성 ─────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 960,
    height: 680,
    minWidth: 720,
    minHeight: 520,
    title: "VOXScript",
    // icon: path.join(__dirname, "assets", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    backgroundColor: "#0f1117",
    show: false, // 로딩 완료 후 표시
  });

  if (DEV_MODE) {
    // 개발: Vite dev server
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
    mainWindow.webContents.openDevTools();  
  }

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });
}

// ── 앱 생명주기 ──────────────────────────────────────────
app.whenReady().then(async () => {
  startBackend();

  try {
    await waitForBackend();
    console.log("[Electron] 백엔드 준비 완료");
  } catch (e) {
    console.error("[Electron] 백엔드 시작 실패:", e.message);
    // 백엔드 없어도 창은 열기 (에러 표시)
  }

  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProcess) {
    console.log("[Electron] 백엔드 종료 중...");
    backendProcess.kill("SIGTERM");
  }
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});

// ── IPC: 파일 선택 다이얼로그 ────────────────────────────
ipcMain.handle("select-file", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "음원/영상 파일 선택",
    filters: [
      { name: "미디어 파일", extensions: ["mp4", "mp3", "mkv", "mov", "avi", "wav", "m4a"] },
      { name: "전체 파일", extensions: ["*"] },
    ],
    properties: ["openFile"],
  });
  return result.canceled ? null : result.filePaths[0];
});

// ── IPC: API 포트 전달 ────────────────────────────────────
ipcMain.handle("get-api-port", () => API_PORT);
