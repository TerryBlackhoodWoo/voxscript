/**
 * VOXScript - Electron Preload
 * contextIsolation=true 환경에서 React ↔ Electron IPC 브릿지
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("voxscript", {
  // 로컬 파일 선택 다이얼로그
  selectFile: () => ipcRenderer.invoke("select-file"),

  // API 포트 가져오기
  getApiPort: () => ipcRenderer.invoke("get-api-port"),

  // 파일 열기
  openFile: (path) => ipcRenderer.invoke("open-file", path),

  // 폴더 열기
  openFolder: (path) => ipcRenderer.invoke("open-folder", path),
});