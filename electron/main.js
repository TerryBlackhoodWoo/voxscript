/**
 * VOXScript - Electron Main Process
 * Launches FastAPI backend in background and displays React UI
 */

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const API_PORT = 8765;
const DEV_MODE = process.env.NODE_ENV === "development";

let mainWindow = null;
let backendProcess = null;


// ── Start Backend ─────────────────────────────────────────
function startBackend() {
  const backendDir = path.join(__dirname, "..", "backend");

  const pythonCmd = app.isPackaged
    ? path.join(process.resourcesPath, "python", "python.exe")
    : "python";

  const scriptPath = path.join(backendDir, "main.py");

  console.log(`[Electron] Backend starting: ${pythonCmd} ${scriptPath}`);

  backendProcess = spawn(pythonCmd, [scriptPath], {
    cwd: backendDir,
    env: {
      ...process.env,
      VOXSCRIPT_PORT: String(API_PORT),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.on("data", (data) => {
    const lines = data.toString('utf-8').trim().split('\n')
    lines.forEach(line => {
      if (line.trim()) process.stdout.write(`[Backend] ${line.trim()}\n`)
    })
  });
  backendProcess.stderr.on("data", (data) => {
    const lines = data.toString('utf-8').trim().split('\n')
    lines.forEach(line => {
      if (!line.trim()) return
      if (line.includes('%|') || line.includes('frames/s')) {
        process.stdout.write(`\r[Whisper] ${line.trim()}`)
      } else {
        process.stdout.write(`[Backend ERR] ${line.trim()}\n`)
      }
    })
  });
  backendProcess.on("exit", (code) => {
    if (code === 0) {
      console.log(`[Backend] Exited normally`)
    } else {
      console.error(`[Backend] Exited with error code: ${code}`)
    }
  });
}

// ── Wait for Backend ──────────────────────────────────────
function waitForBackend(retries = 20, interval = 500) {
  return new Promise((resolve, reject) => {
    const check = (remaining) => {
      if (remaining <= 0) {
        reject(new Error("Backend startup timeout"));
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

// ── Create Main Window ────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    title: "VOXScript",
    // icon: path.join(__dirname, "assets", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    backgroundColor: "#0f1117",
    show: false,
  });

  if (DEV_MODE) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
    mainWindow.webContents.openDevTools();
  }

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });
}

// ── App Lifecycle ─────────────────────────────────────────
app.whenReady().then(async () => {
  startBackend();

  try {
    await waitForBackend();
    console.log("[Electron] Backend ready");
  } catch (e) {
    console.error("[Electron] Backend startup failed:", e.message);
  }

  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProcess) {
    console.log("[Electron] Stopping backend...");
    backendProcess.kill("SIGTERM");
  }
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});

// ── IPC: File Dialog ──────────────────────────────────────
ipcMain.handle("select-file", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Select audio/video file",
    filters: [
      { name: "Media files", extensions: ["mp4", "mp3", "mkv", "mov", "avi", "wav", "m4a"] },
      { name: "All files", extensions: ["*"] },
    ],
    properties: ["openFile"],
  });
  return result.canceled ? null : result.filePaths[0];
});

// ── IPC: API Port ─────────────────────────────────────────
ipcMain.handle("get-api-port", () => API_PORT);

// ── IPC: Pipeline ─────────────────────────────────────────
ipcMain.handle("start-pipeline", async (event, settings) => {
  try {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: settings.sourceUrl,
        language: settings.lang,
        formats: [settings.format],
        use_summary: !settings.noSummary,
        diarize: settings.diarize,
        speakers: settings.diarize ? settings.speakers : [],
      }),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return await response.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// ── IPC: Job Status ───────────────────────────────────────
ipcMain.handle("get-status", async (event, jobId) => {
  try {
    const response = await fetch(`http://127.0.0.1:${API_PORT}/status/${jobId}`);
    return await response.json();
  } catch {
    return { status: "error", error: "Connection failed" };
  }
});