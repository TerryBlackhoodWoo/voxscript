/**
 * VOXScript - Electron Main Process
 * Launches FastAPI backend in background and displays React UI
 */

const { app, BrowserWindow, ipcMain, dialog, safeStorage } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const API_PORT = 8765;
const DEV_MODE = process.env.NODE_ENV === "development";

let mainWindow = null;
let backendProcess = null;

// ── Resolve bundled binaries (ffmpeg / ffprobe / yt-dlp) ──
function getBinaryDir() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "bin")
    : path.join(__dirname, "..", "resources", "bin");
}

function resolveBundledBinary(name) {
  const fs = require("fs");
  const exeName = process.platform === "win32" ? `${name}.exe` : name;
  const exePath = path.join(getBinaryDir(), exeName);
  return fs.existsSync(exePath) ? exePath : null;
}

// ── Start Backend ─────────────────────────────────────────
function startBackend() {
  const fs = require("fs");

  let command;
  let args;
  let backendDir;

  if (app.isPackaged) {
    // 패키징된 빌드: PyInstaller로 빌드한 standalone 백엔드 exe를 그대로 실행.
    // 사용자 PC에 Python이 설치돼 있는지 여부와 무관하게 동작함.
    backendDir = path.join(process.resourcesPath, "backend");
    const exeName = process.platform === "win32" ? "voxscript-backend.exe" : "voxscript-backend";
    command = path.join(backendDir, exeName);
    args = [];
    console.log(`[Electron] Packaged backend: ${command}`);
  } else {
    // 개발 모드: 시스템 Python으로 main.py 직접 실행 (기존 동작 유지)
    backendDir = path.join(__dirname, "..", "backend");
    const os = require("os");
    const home = os.homedir();
    const localAppData = process.env.LOCALAPPDATA
      || path.join(home, "AppData", "Local");
    const candidates = [
      path.join(localAppData, "Programs", "Python", "Python311", "python.exe"),
      path.join(localAppData, "Programs", "Python", "Python312", "python.exe"),
      path.join(localAppData, "Programs", "Python", "Python310", "python.exe"),
      path.join(localAppData, "Programs", "Python", "Python313", "python.exe"),
      "python",
      "python3",
    ];
    command = candidates.find(p => {
      try { return p === "python" || p === "python3" || fs.existsSync(p); } catch { return false; }
    }) || "python";
    args = [path.join(backendDir, "main.py")];
    console.log(`[Electron] Dev backend: ${command} ${args.join(" ")}`);
  }

  // 번들된 ffmpeg / ffprobe / yt-dlp 경로를 env var로 전달.
  // 없으면(=dev 모드에서 resources/bin이 비어있을 때) 설정하지 않고
  // Python 쪽(DAO/bin_paths.py)이 시스템 PATH로 폴백하게 둠.
  const extraEnv = {};
  const ffmpegPath = resolveBundledBinary("ffmpeg");
  const ffprobePath = resolveBundledBinary("ffprobe");
  const ytdlpPath = resolveBundledBinary("yt-dlp");
  const denoPath = resolveBundledBinary("deno");
  if (ffmpegPath) extraEnv.FFMPEG_PATH = ffmpegPath;
  if (ffprobePath) extraEnv.FFPROBE_PATH = ffprobePath;
  if (ytdlpPath) extraEnv.YTDLP_PATH = ytdlpPath;
  if (denoPath) extraEnv.DENO_PATH = denoPath;
  console.log("[Electron] Bundled binaries:", { ffmpegPath, ffprobePath, ytdlpPath });

  backendProcess = spawn(command, args, {
    cwd: backendDir,
    env: {
      ...process.env,
      ...extraEnv,
      VOXSCRIPT_PORT: String(API_PORT),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.on("data", (data) => {
    const lines = data.toString('utf-8').trim().split('\n')
    lines.forEach(line => {
      if (line.trim()) console.log(`[Backend] ${line.trim()}`)
    })
  });
  backendProcess.stderr.on("data", (data) => {
    const lines = data.toString('utf-8').trim().split('\n')
    lines.forEach(line => {
      if (!line.trim()) return
      // Whisper tqdm 진행바는 ERR로 나오지만 정상이라 구분
      if (line.includes('%|') || line.includes('frames/s')) {
        process.stdout.write(`\r[Whisper] ${line.trim()}`)
      } else {
        console.error(`[Backend ERR] ${line.trim()}`)
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
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    backgroundColor: "#fffaf5",
    show: false,
  });

  if (DEV_MODE) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();  // 개발 모드에서만 열기
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"));
    // 프로덕션에서는 DevTools 끄기
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
    dialog.showErrorBox(
      "VOXScript 백엔드 시작 실패",
      "백엔드 서버가 정상적으로 시작되지 않았습니다.\n" +
      "앱을 다시 실행해보거나, 문제가 계속되면 로그를 확인해주세요.\n\n" +
      `(${e.message})`
    );
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

// ── IPC: Open File ────────────────────────────────────────
ipcMain.handle("open-file", async (event, filePath) => {
  const { shell } = require("electron");
  const path = require("path");
  const outputDir = path.join(
    require("os").homedir(),
    "Downloads", "VOXScript", "output"
  );
  const fullPath = filePath.includes("\\") || filePath.includes("/")
    ? filePath
    : path.join(outputDir, filePath);
  await shell.openPath(fullPath);
});

// ── IPC: Open Folder ──────────────────────────────────────
ipcMain.handle("open-folder", async (event, filePath) => {
  const { shell } = require("electron");
  const path = require("path");
  const outputDir = path.join(
    require("os").homedir(),
    "Downloads", "VOXScript", "output"
  );
  const fullPath = filePath.includes("\\") || filePath.includes("/")
    ? path.dirname(filePath)
    : outputDir;
  await shell.openPath(fullPath);
});

// ── IPC: 인증 토큰 저장 (safeStorage) ──────────────────────
function getTokenPath() {
  const path = require("path");
  return path.join(app.getPath("userData"), "auth_token.enc");
}

ipcMain.handle("save-token", (event, token) => {
  const fs = require("fs");
  if (!safeStorage.isEncryptionAvailable()) {
    console.error("[Electron] safeStorage not available on this system");
    return false;
  }
  fs.writeFileSync(getTokenPath(), safeStorage.encryptString(token));
  return true;
});

ipcMain.handle("load-token", () => {
  const fs = require("fs");
  const tokenPath = getTokenPath();
  if (!fs.existsSync(tokenPath)) return null;
  try {
    return safeStorage.decryptString(fs.readFileSync(tokenPath));
  } catch (e) {
    console.error("[Electron] Failed to decrypt token:", e.message);
    return null;
  }
});

ipcMain.handle("clear-token", () => {
  const fs = require("fs");
  const tokenPath = getTokenPath();
  if (fs.existsSync(tokenPath)) fs.unlinkSync(tokenPath);
  return true;
});

// ── IPC: 백엔드 API 공통 호출 헬퍼 ─────────────────────────
async function callApi(method, path, body) {
  try {
    const response = await fetch(`http://127.0.0.1:${API_PORT}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail || `API error: ${response.status}`;
      return { ok: false, error: detail };
    }
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ── IPC: 1단계 시작 — 다운로드 → STT → Gemini 전처리 → 라벨링 대기 ──
// settings: { source, lang, targetLang, format, modelSize, useSummary }
ipcMain.handle("start-pipeline", async (event, settings) => {
  return callApi("POST", "/start", {
    source: settings.source,
    lang: settings.lang ?? "auto",
    target_lang: settings.targetLang ?? "KO",
    format: settings.format ?? "all",
    model_size: settings.modelSize ?? "medium",
    use_summary: settings.useSummary ?? true,
  });
});

// ── IPC: 2단계 완료 — 라벨링 결과 반영 → 화자 fill + 번역 ──
// payload: { labeledSegments: [{index, speaker}], speakers: ["이름1", "이름2"] }
ipcMain.handle("resume-pipeline", async (event, projectId, payload) => {
  return callApi("POST", `/resume/${projectId}`, {
    labeled_segments: payload?.labeledSegments ?? [],
    speakers: payload?.speakers ?? [],
  });
});

// ── IPC: 5단계 — 최종 포맷 변환 + 파일 저장 ──
// payload: { exportDir, formats }
ipcMain.handle("save-output", async (event, projectId, payload) => {
  return callApi("POST", `/save/${projectId}`, {
    export_dir: payload?.exportDir ?? null,
    formats: payload?.formats ?? null,
  });
});

// ── IPC: 진행 상태 + 로그 조회 (폴링용) ──
ipcMain.handle("get-status", async (event, projectId) => {
  return callApi("GET", `/status/${projectId}`);
});

// ── IPC: 저장된 프로젝트 목록 (사이드바용) ──
ipcMain.handle("get-projects", async () => {
  return callApi("GET", "/projects");
});

// ── IPC: 저장된 프로젝트 이어하기 ──
ipcMain.handle("load-project", async (event, projectId) => {
  return callApi("GET", `/load/${projectId}`);
});

// ── IPC: 지원 언어 목록 ──
ipcMain.handle("get-languages", async () => {
  return callApi("GET", "/languages");
});

// ── IPC: 출력 포맷 목록 ──
ipcMain.handle("get-formats", async () => {
  return callApi("GET", "/formats");
});