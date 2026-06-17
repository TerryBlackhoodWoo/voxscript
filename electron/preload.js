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

  // 1단계 시작: 다운로드 → STT → Gemini 전처리 → 라벨링 대기
  startPipeline: (settings) => ipcRenderer.invoke("start-pipeline", settings),

  // 2단계 완료: 라벨링 결과 반영 → 화자 fill + 번역
  resumePipeline: (projectId, payload) =>
    ipcRenderer.invoke("resume-pipeline", projectId, payload),

  // 5단계: 최종 포맷 변환 + 파일 저장
  saveOutput: (projectId, payload) =>
    ipcRenderer.invoke("save-output", projectId, payload),

  // 진행 상태 + 로그 조회 (폴링용)
  getStatus: (projectId) => ipcRenderer.invoke("get-status", projectId),

  // 저장된 프로젝트 목록 (사이드바용)
  getProjects: () => ipcRenderer.invoke("get-projects"),

  // 저장된 프로젝트 이어하기
  loadProject: (projectId) => ipcRenderer.invoke("load-project", projectId),

  // 지원 언어 목록
  getLanguages: () => ipcRenderer.invoke("get-languages"),

  // 출력 포맷 목록
  getFormats: () => ipcRenderer.invoke("get-formats"),
});