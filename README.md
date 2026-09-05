# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 도구

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/Electron-32-47848F)](https://www.electronjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.4.0-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-Vite-61dafb)](https://vitejs.dev/)
[![Release](https://img.shields.io/github/v/release/TerryBlackhoodWoo/voxscript)](https://github.com/TerryBlackhoodWoo/voxscript/releases/latest)

---

## 프로젝트 소개

> 🖥️ **배포 형태**: Windows 데스크탑 앱 (NSIS 인스톨러, PyInstaller로 백엔드까지 단일 실행파일화 — 사용자 PC에 Python 설치 불필요)
> **다운로드**: [GitHub Releases](https://github.com/TerryBlackhoodWoo/voxscript/releases/latest) — 단, API 키/OAuth 자격증명은 배포판에 포함돼 있지 않아 별도 설정 필요 (아래 [환경 설정](#환경-설정) 참고)

**Whisper API(STT) + DeepL(번역) + Gemini(전처리/화자구분/요약)** 파이프라인으로
YouTube / Google Drive / 로컬 파일을 자동으로 번역 스크립트로 변환하는 Electron 데스크탑 앱입니다.

### 기획 배경

실제 사용자(방송 작가)가 스페인어 다큐멘터리 인터뷰 영상을 매번 외주로 번역·정리하던 비효율을 직접 겪고 시작한 프로젝트입니다.

**STT 결과의 노이즈**
- Whisper STT 결과는 중복 발화, 문장 중간 겹침, 어색한 줄바꿈이 항상 섞여 있음
- "받아쓰기"와 "그대로 쓸 수 있는 스크립트" 사이 간극이 커서, 이 간극을 메우는 전처리 단계를 Gemini로 분리해서 해결

**화자 구분 방식**
- pyannote 같은 음성/영상 기반 화자분리 모델은 무겁고 GPU 의존적
- 대신 **번역된 텍스트의 대화 패턴**으로 화자를 추론하는 방식 채택 — 질문/응답 길이, 짧은 반응 패턴 등으로 인터뷰어·인터뷰이를 구분

**긴 영상 처리 안정성**
- 1시간 단위 STT를 한 번에 돌리면 중간에 실패할 경우 처음부터 다시 해야 하는 문제
- 단계별 파이프라인(다운로드 → STT/전처리 → **유저 라벨링 대기** → 화자 fill/번역 → 저장)으로 분리하고, `.vox` 프로젝트 파일로 중간 상태를 저장해 이어하기를 지원

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| Desktop Shell | Electron 32 |
| Frontend | React + Vite (별도 레포: `voxscript_frontend`) |
| Backend | Python 3.11, FastAPI, Uvicorn |
| STT | OpenAI Whisper API (기본) / 로컬 Whisper(CUDA) — dev 환경 전용 폴백 |
| 전처리·화자구분·요약 | Google Gemini (`google-genai`, `gemini-2.5-flash`) |
| 번역 | DeepL API |
| 다운로드 | yt-dlp (YouTube), Google Drive API (OAuth 2.0), 로컬 파일 |
| 미디어 처리 | ffmpeg / ffprobe |
| 패키징 | PyInstaller (백엔드 단일 실행파일화), electron-builder (NSIS/DMG) |

---

## 핵심 설계 포인트

### 1. 텍스트 기반 화자 구분
```
음성 기반 화자분리(pyannote 등) 대신
번역된 텍스트의 대화 패턴으로 화자 추론

1단계: 역할 추론 (gemini-2.5-flash)
       - 전체 구간 중 10~40% 지점 샘플링 (오프닝/내레이션 구간 제외)
       - 질문 빈도/짧은 반응 → 인터뷰어, 긴 설명/답변 → 인터뷰이 판단
2단계: 청크별(50세그먼트) 라벨링
       - 1단계에서 정한 역할 기준으로 전체 세그먼트에 라벨 배정
       - JSON 파싱 실패 시 1회 재시도, 그래도 실패하면 인터뷰이로 기본값 처리

→ GPU/무거운 오디오 분리 모델 없이 텍스트만으로 화자 구분 가능
```

### 2. 단계별 파이프라인 + `.vox` 프로젝트 파일 (이어하기 지원)
```
1시간 영상 STT를 한 번에 처리하면 중간 실패 시 처음부터 재시작해야 함
→ 5단계로 분리하고, 각 분기점마다 .vox 파일로 상태 저장

[다운로드 → STT → Gemini 전처리] → ⏸ 라벨링 대기(유저 개입)
       → [화자 자동 fill → 번역] → ⏸ 저장 대기(경로 선택)
       → [포맷 변환 → 파일 저장]

저장 구조: {project_dir}/{원본이름}_{project_id}.vox (평면 저장)
GET /load/{project_id}로 서버 재시작 후에도 이어서 진행 가능
```

### 3. Whisper API 24MB 제한 우회 — 자동 청크 분할
```
OpenAI Whisper API 단일 요청 한도: 25MB

ffprobe로 전체 길이 측정
→ 20분 단위로 청크 분할 (24MB 여유 있게)
→ 각 청크 독립 호출 후, 세그먼트 타임스탬프에 offset(청크 시작 시간) 적용해 재조립

→ 1시간 이상 영상도 끊김 없이 하나의 타임라인으로 처리
```

### 4. Gemini 전처리 병렬화
```
Whisper STT 결과는 중복 발화/문장 겹침이 항상 섞여 있음

150세그먼트 단위로 청크 분할
→ ThreadPoolExecutor(max_workers=3)로 동시 호출
→ 청크별 결과를 원래 순서대로 재조립 (chunk_start 기준 정렬)
→ JSON 파싱 실패 시 1회 재시도, 그래도 실패하면 원본 세그먼트 그대로 보존 (데이터 손실 방지)
```

### 5. 배포 바이너리 경로 일원화 (`bin_paths.py`)
```
Electron 패키징 빌드: main.js가 FFMPEG_PATH / FFPROBE_PATH / YTDLP_PATH
환경변수로 번들된 바이너리 절대경로 주입

개발 모드: 환경변수 없으면 시스템 PATH에서 탐색
          그것도 없으면 원래 이름 그대로 반환 → subprocess가
          명확한 FileNotFoundError를 던지게 설계

→ 어디서 실행되든 ffmpeg/ffprobe/yt-dlp 호출 코드는 한 줄도 안 바꿔도 됨
```

### 6. YouTube JS 런타임 대응 (`deno` 연동)
```
YouTube가 영상 URL 서명 검증에 브라우저 수준 JS 실행을 요구하도록 변경
→ JS 런타임 없는 yt-dlp 단독 호출은 403 Forbidden

resources/bin/deno.exe를 같이 배포
→ bin_paths.get_deno()로 경로 해석 (ffmpeg/ffprobe/yt-dlp와 동일한 패턴)
→ yt-dlp 호출 시 --js-runtimes deno:<path> 전달 (제목 추출 / 오디오 추출 둘 다)

→ 외부 서비스 정책 변화에 맞춰 무거운 브라우저 엔진 없이 대응
```

---

## 빠른 시작

### Electron 앱 모드 (개발)
```bash
npm install
npm run build
npm run electron
```

### CLI 모드
```bash
cd backend
pip install -r requirements.txt
python pipeline.py "https://drive.google.com/drive/folders/FOLDER_ID" --lang en --format all
python pipeline.py "./video.mp4" --lang ja --format all --diarize --speakers 진행자 게스트
```

### 배포용 패키징 (Windows 인스톨러)
ffmpeg/ffprobe/yt-dlp 바이너리와 컴파일된 Python 백엔드를 통째로 묶어서, 사용자 PC에 Python/ffmpeg가 전혀 없어도 동작하는 단일 인스톨러를 만듭니다.

```bash
# 1) ffmpeg.exe / ffprobe.exe / yt-dlp.exe / deno.exe를 resources/bin/ 에 받아넣기
#    - ffmpeg: https://github.com/BtbN/FFmpeg-Builds/releases
#    - yt-dlp: https://github.com/yt-dlp/yt-dlp/releases
#    - deno: https://github.com/denoland/deno/releases (deno-x86_64-pc-windows-msvc.zip 안의 deno.exe)
#            yt-dlp가 YouTube 서명 검증용 JS 런타임으로 사용 (없으면 403 Forbidden 발생)

# 2) 백엔드를 PyInstaller로 단일 실행파일화 (backend-dist/voxscript-backend/ 생성)
yarn build:backend

# 3) 프론트엔드 빌드 + electron-builder 패키징
yarn package
```

### 환경 설정

| 키 | 발급처 | 비용 | 용도 |
|---|---|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com | $0.006/분 | Whisper STT |
| `GEMINI_API_KEY` | https://console.cloud.google.com | 유료 | 전처리/화자구분/요약 |
| `DEEPL_API_KEY` | https://www.deepl.com/ko/pro-api | 월 500,000자 무료 | 번역 |

Google Drive 다운로드 기능은 API 키가 아니라 **OAuth 2.0 흐름**을 씁니다. Google Cloud Console에서 OAuth 클라이언트(Desktop App 타입)를 만들어 `backend/credentials.json`으로 저장하면, 최초 실행 시 브라우저가 열려 로그인 → `backend/token.json`이 자동 생성됩니다. 두 파일 + `.env` 모두 개인 인증 정보이므로 `.gitignore`에 반드시 포함하고 절대 커밋하지 마세요.

---

## 파이프라인 흐름

```
[1단계] 다운로드 → Whisper STT → Gemini 전처리
    ↓
[2단계] ⏸ 스크립트 편집 + 화자 라벨링 (유저 개입)
         · 텍스트 인라인 편집
         · 행 분리 (✂) — 커서 위치 기준, 타임스탬프 자동 분배
         · 행 병합 (⊕) — 아래 행과 합치기
         · 화자 드롭다운 지정 / 확인 or 스킵
    ↓
[3단계] 나머지 화자 자동 fill (유저 지정 이름 우선)
    ↓
[4단계] 번역 (한국어 소스면 스킵)
    ↓
[5단계] 저장 경로 선택 → 파일 저장 → .vox 프로젝트 파일 저장
```

---

## API 엔드포인트

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| GET | `/` | 헬스체크 |
| GET | `/languages` | 지원 원본/번역 언어 목록 |
| GET | `/formats` | 출력 포맷 목록 (txt/srt/excel 등) |
| GET | `/projects` | 저장된 프로젝트 목록 (사이드바용) |
| POST | `/start` | 1~3단계 실행 — 다운로드 → Whisper STT → Gemini 전처리 → 라벨링 대기 (백그라운드 스레드) |
| GET | `/status/{project_id}` | 진행 상태 + 로그 조회 (폴링용) |
| POST | `/resume/{project_id}` | 유저 라벨링 결과 반영 → 화자 자동 fill + 번역 진행 |
| POST | `/save/{project_id}` | 최종 포맷 변환 + 파일 저장 (`stage != saving`이면 400) |
| GET | `/load/{project_id}` | 저장된 `.vox` 프로젝트 이어하기 |

> `/start`, `/resume`, `/save`는 모두 백그라운드 스레드에서 실행되고, 프론트엔드는 `/status/{project_id}`를 폴링해서 진행률·로그를 받아오는 구조입니다.
> **실제 통신 구조**: `voxscript_frontend`의 `App.jsx`가 위 엔드포인트들을 `http://localhost:8765`로 직접 `fetch` 호출합니다 (Electron IPC를 경유하지 않음). Electron `main.js`/`preload.js`의 `window.voxscript` 브릿지는 `selectFile`/`openFile`/`openFolder` 같은 **네이티브 OS 다이얼로그 전용**으로만 쓰입니다. `main.js`에 있는 `startPipeline`/`resumePipeline`/`saveOutput`/`getStatus`/`getProjects`/`loadProject`/`getLanguages`/`getFormats` IPC 핸들러는 현재 프론트엔드에서 호출되지 않는 상태입니다 (추후 IPC 경유 구조로 바꿀 경우를 위해 남겨둔 상태, 당장 정리 대상은 아님).
> 포트(8765)는 `main.js`/`main.py`(`VOXSCRIPT_PORT` env var, 기본값 8765)/`App.jsx`(하드코딩) 세 군데서 각각 따로 맞춰져 있는 상태라, 셋 중 하나라도 바뀌면 나머지도 같이 바꿔야 함.

---

## 프로젝트 구조

```
voxscript/
├── backend/
│   ├── main.py                  ← FastAPI 서버 (v0.4.0 단계별 파이프라인)
│   ├── pipeline.py              ← CLI 모드 진입점
│   ├── project_schema.py        ← VoxProject(.vox) 파일 스키마
│   ├── requirements.txt
│   ├── voxscript-backend.spec   ← PyInstaller 빌드 스펙
│   ├── credentials.json         ← Google OAuth 클라이언트 (gitignore 필수, 커밋 금지)
│   ├── token.json               ← Google OAuth 토큰, 최초 인증 시 자동 생성 (gitignore 필수)
│   └── DAO/
│       ├── __init__.py
│       ├── bin_paths.py         ← ffmpeg/ffprobe/yt-dlp 경로 해석 (env var → PATH 폴백)
│       ├── downloader.py        ← YouTube(yt-dlp) / Google Drive / 로컬 파일
│       ├── transcriber.py       ← Whisper API (기본) / 로컬 Whisper CUDA (dev 전용)
│       ├── cleaner.py           ← Gemini 전처리 (병렬처리, 중복 제거, Q&A 구조 보존)
│       ├── translator.py        ← DeepL 번역 (한국어 소스 자동 스킵)
│       ├── diarizer.py          ← Gemini 텍스트 기반 화자 구분 (유저 지정 이름 우선)
│       └── formatter.py         ← TXT/SRT/Excel 저장 + Gemini 요약
├── electron/
│   ├── main.js                  ← Electron 메인 (백엔드 spawn, 바이너리 경로 주입, IPC)
│   ├── preload.js               ← contextBridge IPC 브릿지
│   └── assets/
│       └── icon.ico / icon.icns
├── package.json
└── .env.example
voxscript_frontend/              ← React 19 + Vite UI (별도 레포)
├── public/
│   ├── favicon.svg
│   └── icons.svg
├── src/
│   ├── assets/
│   │   ├── VOXScriptLogo.png
│   │   ├── hero.png
│   │   └── react.svg / vite.svg
│   ├── components/
│   │   ├── Sidebar.jsx          ← 프로젝트 목록 + 단계(stage) 라벨 표시
│   │   ├── SettingsPanel.jsx    ← 시작 설정 (언어 / 번역 타겟 / 출력 포맷 선택)
│   │   ├── ScriptView.jsx       ← 진행률 바 + 결과 스크립트 뷰, 파일/폴더 열기
│   │   ├── LabelingView.jsx     ← 라벨링 화면 (행 분리 ✂ / 병합 ⊕, 화자 지정)
│   │   └── SavePanel.jsx        ← 저장 포맷 선택 + 저장 경로 지정
│   ├── App.jsx                  ← 단계(STAGE) 전환 관리, 백엔드 API 직접 fetch 호출
│   ├── App.css / index.css
│   └── main.jsx
├── eslint.config.js
├── vite.config.js
├── package.json
└── yarn.lock


voxscript_design/                ← 아이콘 디자인 일러스트

resources/
    └── bin/                     ← 배포용 바이너리 (gitignore, 빌드 전 별도 다운로드)
        ├── ffmpeg.exe
        ├── ffprobe.exe
        ├── yt-dlp.exe
        └── deno.exe             ← yt-dlp의 YouTube JS 런타임 (서명 검증용)


```

---

## 개발 현황

> 초기 버전(v0.1.0~v1.0.0)은 날짜 기록 없이 진행돼서 버전 번호로만 구분합니다.

### v0.1.0 — CLI 파이프라인
- [x] argparse 기반 CLI 진입점 (`pipeline.py`)
- [x] 다운로드 → STT → 전처리 → 번역 → 포맷 저장 단일 흐름

### v0.2.0 — Electron 데스크탑 앱
- [x] Electron 메인 프로세스 + React 프론트엔드 골격
- [x] contextBridge 기반 IPC 브릿지 (`preload.js`)

### v0.3.0 — Whisper API + Gemini 병렬처리 + 한국어 최적화
- [x] OpenAI Whisper API 도입 (기존 로컬 Whisper CUDA는 dev 전용 폴백으로 유지, `OPENAI_API_KEY` 유무로 자동 분기)
- [x] Gemini 전처리를 `ThreadPoolExecutor(max_workers=3)`로 병렬화해 처리 속도 개선
- [x] 한국어 소스 감지 시 DeepL 번역 자동 스킵

### v0.4.0 — 단계별 파이프라인 + 화자 라벨링 UI + 프로젝트 파일
- [x] CLI 단일 흐름 → FastAPI 백엔드로 전환, 1~5단계로 분리
- [x] `.vox` 프로젝트 파일 도입 — 단계 전환마다 상태 저장, 라벨링 대기 시점에 유저 개입 지점 확보
- [x] 화자 라벨링 UI 1차 버전

### v0.5.0 — UI 최적화
- [x] 중앙 뷰 프로젝트 요약 표시
- [x] 파일 목록 + 열기 버튼
- [x] Inter + Noto Sans KR 폰트

### v0.6.0 — 스크립트 편집 UI
- [x] `LabelingView.jsx`에 Vrew 스타일 인라인 편집 도입
- [x] 행 분리(✂) / 병합(⊕) — 분리 시 타임스탬프를 문자 비율(character-ratio) 기준으로 자동 분배
- [x] 화자 드롭다운 (기본값 미지정, 스킵 가능)

### v1.0.0 — 배포 + 자동 업데이트
- [x] electron-builder로 NSIS 인스톨러 패키징 (약 80MB)
- [x] 앱 아이콘 적용
- [ ] 자동 업데이트(electron-updater) — 미구현, 보류

### v1.1.0 — 오프라인 배포 패키징
- [x] ffmpeg/ffprobe/yt-dlp 하드코딩 호출 제거 → `DAO/bin_paths.py`로 경로 해석 일원화
- [x] PyInstaller 백엔드 빌드 스펙 작성 + 실제 빌드/구동 검증 (`google.genai`, `googleapiclient` hidden import 포함)
- [x] `googleapiclient`가 기본으로 끌고 오는 discovery 문서 정리 (Drive v3만 남기고 나머지 제거, 97MB → 1MB)
- [x] **`.vox` 프로젝트 저장 경로 불일치 버그 수정** — `save_project()`는 `{project_dir}/{이름}_{project_id}.vox` 형태로 평평하게 저장하는데, `main.py`의 `/status`·`/load`는 `{project_id}/project.vox`라는 존재하지 않는 하위 폴더 구조를 찾고 있어서 서버 재시작 후 "프로젝트 이어하기"가 항상 실패하던 문제 발견. `find_project_file()` 헬퍼를 추가해 동일한 flat glob 패턴(`*_{project_id}.vox`)으로 통일
- [x] **Electron ↔ 백엔드 API 스키마 불일치 수정** — `main.js`가 실제로는 존재하지 않는 `/process` 엔드포인트를 호출하고 있었고 필드명(`language`/`formats` 등)도 실제 스키마와 달랐음. `/resume`·`/save`·`/projects`·`/load`에 대응하는 IPC 핸들러 자체가 없어서 5단계 파이프라인과 전혀 연동이 안 되는 상태였던 것을 발견 → `/start`·`/resume/{id}`·`/save/{id}`·`/status/{id}`·`/projects`·`/load/{id}`·`/languages`·`/formats`에 맞춰 IPC 핸들러 전면 재작성, `preload.js`에 노출
- [x] **PyInstaller frozen 빌드의 OAuth 자격증명 경로 버그 수정** — `downloader.py`의 `CREDENTIALS_PATH`가 `Path(__file__).parent.parent` 기준이라 onedir 빌드에서 `_internal/` 폴더 안쪽을 가리키게 됨(exe와 한 단계 어긋남) → `sys.frozen` 여부에 따라 `sys.executable` 기준으로 분기하도록 수정
- [x] `/save` 엔드포인트에 `stage != SAVING`이면 400 반환하는 방어 코드 추가, 백엔드 기동 실패 시 `dialog.showErrorBox`로 사용자 안내 추가
- [x] **`.gitignore` 정비** — 패키징 빌드 산출물(`dist/`, `backend-dist/`) 경유로 `credentials.json`/`token.json`이 함께 묶여 나가던 것을 확인 → 해당 OAuth 클라이언트 재발급 후 `.gitignore`에 `dist/`, `backend-dist/`, `credentials.json`, `token.json`, `.env` 전부 등록해 재발 방지
- [x] `downloader.py` docstring 내용 수정 (YouTube가 yt-dlp 기반으로 실제 지원 중이라는 사실에 맞게 정정)
- [x] **PyInstaller 빌드 용량 축소 (294MB → ~95MB)** — `openai-whisper`(배포판 미사용, dev 전용 폴백)가 끌고 오는 `numba`/`llvmlite`/`scipy`/`pandas`를 spec `excludes`에 추가
- [x] ffmpeg/ffprobe/yt-dlp 바이너리 `resources/bin/`에 실제 배치 + 실기기에서 standalone 구동 확인
- [x] **YouTube 다운로드 시 yt-dlp 403 Forbidden 수정** — YouTube가 영상 URL 서명 검증에 JS 실행을 요구하도록 바뀌면서, JS 런타임 없는 yt-dlp 단독 호출이 막힘 → `deno` 런타임을 `resources/bin/`에 추가 배포, `bin_paths.get_deno()` + `downloader.py`의 두 yt-dlp 호출(제목 추출/오디오 추출)에 `--js-runtimes deno:<path>` 전달, `main.js`에 `DENO_PATH` 환경변수 주입
- [x] **Windows 한국어 콘솔(cp949) 인코딩 크래시 수정** — frozen exe에서 `print()`에 이모지(예: `⏸`)가 들어가면 `cp949` 코덱이 인코딩 못 해서 파이프라인 전체가 죽던 문제. `main.js`에 이미 `PYTHONUTF8`/`PYTHONIOENCODING` env var가 있었음에도 frozen 빌드에서 안정적으로 반영 안 되는 PyInstaller 특성 확인 → `main.py`에서 `sys.stdout`/`sys.stderr`를 UTF-8로 직접 재설정(`errors="replace"` 포함)하는 방식으로 보완
- [x] 실기기 인스톨러 테스트로 로컬 파일 + YouTube + Google Drive 다운로드 → STT → Gemini 전처리 → 라벨링 대기까지 전체 플로우 정상 동작 확인
- [x] **재시작 후 "좀비 상태" 프로젝트 처리** — 다운로드/STT/전처리/번역 단계 중 앱이 비정상 종료되면, 그 단계를 진행시키던 백그라운드 스레드는 사라지는데 `.vox` 파일엔 그 순간 단계가 그대로 남아있어서 재시작 후 다시 불러오면 멈춘 진행률을 영원히 보여주는 문제 발견 → `/status`·`/load`가 디스크에서 새로 불러올 때 이런 단계면 자동으로 ERROR로 전환하도록 수정 (라벨링/저장 대기는 유저 입력을 기다리는 진짜 일시정지라 예외)
- [x] **사이드바에 라벨링/저장 대기 프로젝트가 안 보이던 문제 수정** — 프론트엔드 프로젝트 목록 필터가 완료/오류 상태만 표시하고 있어서, 재시작 후 이어서 라벨링하려 해도 목록에 아예 안 떠서 클릭할 방법이 없었음 → 필터에 `labeling`/`saving` 단계 추가
- [x] PyInstaller 콘솔창 숨기기 (`console=False`) — 위 항목들 실기기 검증 다 통과한 뒤 최종 적용

> v1.1.0 목표였던 "핵심 파이프라인의 진짜 배포 가능한 상태"는 여기서 마무리.

---

### v1.2.0 — UI 앰버 톤 리스킨
- [x] 전체 컬러 톤을 앰버/오렌지 계열로 리스킨 (사이드바 그라데이션, 설정 패널 다크 네이비 → 크림 톤 재조정)
- [x] 사이드바 헤더에 로고 이미지(`VOXScriptLogo.png`) 적용
- [x] 라벨링 화면 세그먼트 행 편집 UI 색상 체계 정리 (화자별 색상, 분리/병합 버튼 hover 색)

### v1.2.1 — UI 버그 수정
v1.2.0 릴리즈 후 실제 사용 중 발견된 시각적 버그 모음. 전부 `voxscript_frontend` 쪽 수정.
- [x] **다크모드 텍스트 가시성 버그** — `script-title`/`save-title`/`labeling-title`/`save-done-title`(전부 `<h2>`) 클래스에 색이 명시적으로 지정 안 돼있어서, 레거시 `index.css`의 `h1, h2 { color: var(--text-h) }` 규칙을 그대로 물려받음. `--text-h`가 다크모드에서 거의 흰색(`#f3f4f6`)으로 바뀌는 변수라, OS가 다크모드면 크림색 배경 위에 제목 텍스트가 안 보이는 문제 → 4개 클래스에 `color: var(--text-primary)` 명시적으로 추가
- [x] **본문 텍스트 가운데 정렬 버그** — 레거시 `index.css`의 `#root { text-align: center }`(예전 Vite 기본 템플릿 잔재)가 앱 전체에 상속돼서 Gemini 요약 등 본문이 의도와 다르게 가운데 정렬되던 문제 → `.app-layout`에 `text-align: left` 추가, `.summary-content`에도 동일 적용
- [x] **Gemini 요약 마크다운 미반영** — `**굵게**` 같은 마크다운 문법이 그대로 별표 문자로 노출되던 문제 → 별도 라이브러리 없이 가벼운 `renderMarkdownBold()` 헬퍼로 `**...**` 패턴만 `<strong>`으로 변환
- [x] **저장된 파일 목록 글자색 버그** — `.file-name`에 다른 규칙이 끼어들어 흰 글자로 보이던 문제 → `color: var(--text-primary) !important`로 고정

> 다음에 시간 나면: `index.css`(레거시 Vite 스캐폴드 잔재) 자체를 정리해서, 이런 "색 지정 빠뜨리면 다크모드에서 안 보임" 패턴이 또 생기는 걸 근본적으로 막을 것.

### v1.3.0 — Supabase 계정 인증 + 사용량 통제
FABLE 백엔드의 계정/사용량 추적 패턴을 참고해, VOXScript 전용 로그인 인증과 월별 사용량 한도를 새로 도입. Supabase 프로젝트를 FABLE과 공유하되 테이블(`_vox` suffix)과 JWT 시크릿은 완전히 분리.
- [x] Supabase에 `accounts_vox`/`usage_counters_vox`/`processing_logs_vox` 테이블 신설
- [x] `backend/config.py`, `backend/database_pg.py` 신설 — asyncpg 커넥션 풀, `.env` 필수값(`DATABASE_URL`/`VOX_JWT_SECRET`) 누락 시 서버가 즉시 fail-fast
- [x] `backend/services/auth_service.py` — bcrypt 비밀번호 검증, JWT 발급/검증, 5회 로그인 실패 시 15분 계정 잠금
- [x] `POST /login`, `GET /me` 엔드포인트 추가
- [x] `/start`, `/resume/{id}`, `/save/{id}` 전부 `Depends(get_current_account)`로 인증 필수화
- [x] `/start` 호출 시점에 계정별 월간 STT 사용 한도(분 단위) 체크, 초과 시 429 차단
- [x] STT 완료 시 실제 처리 길이를 `usage_counters_vox.stt_seconds`에 자동 누적
- [x] **백그라운드 스레드의 asyncpg 풀 충돌 버그 수정** — `_run_stage1`이 별도 스레드에서 사용량을 기록할 때 `asyncio.run()`으로 새 이벤트 루프를 만들면서, 메인 루프 소속인 커넥션 풀을 건드려 `cannot perform operation: another operation is in progress` 크래시 발생 → `run_coroutine_threadsafe`로 메인 이벤트 루프에 위임하는 방식으로 수정
- [x] 실기기 검증: 로그인 → JWT 발급 → `/start` 인증 통과 → 한도 초과 429 차단 → 유튜브 쇼츠 실제 다운로드~STT 완주 → `stt_seconds` DB 반영까지 전체 플로우 확인

> 프론트엔드 로그인 화면(`voxscript_frontend`)과 Electron `safeStorage` 토큰 저장은 다음 버전으로 이월.

### v1.4.0 — 중앙 인증 서버 분리 (진행 중)
v1.3.0에서 만든 인증/사용량 로직을 데스크탑 앱 로컬 백엔드에 그대로 두면 배포가 불가능하다는 걸 뒤늦게 인지 — PyInstaller onedir 빌드는 사실상 압축 해제하면 소스가 그대로 노출되는 구조라, `.env`를 빌드에 포함시키면 `DATABASE_URL`/`VOX_JWT_SECRET`을 설치한 사람 누구나 평문으로 볼 수 있는 문제였음. 인증/사용량 로직을 별도 중앙 서버로 분리하는 작업 시작.
- [x] 인증/DB 관련 코드(`config.py`, `database_pg.py`, `auth_service.py`, `account_vox_dao.py`, `usage_vox_dao.py`)를 별도 레포 [voxscript_auth_server](https://github.com/TerryBlackhoodWoo/voxscript_auth_server)로 이관
- [x] 중앙 서버에 `/login`, `/me`, `/usage/status`, `/usage/record` HTTPS API 신설, Railway 배포 대상으로 구성 (Procfile 포함)
- [x] `voxscript/backend`에서 DB 직접 연결 제거, `central_client.py`로 중앙 서버 HTTPS 호출하는 방식으로 리팩터
- [x] Railway 실배포 + 로컬 백엔드 ↔ Railway 연동 검증
- [ ] 프론트엔드 로그인 화면(`voxscript_frontend`) + Electron `safeStorage` 토큰 저장

> 완료되면 로컬 백엔드(유저 PC에서 실행되는 프로세스)는 DB 자격증명을 전혀 갖지 않는 상태가 됨 — 인증/과금은 전부 중앙 서버가 담당하고, 로컬은 그 서버를 HTTPS로 호출하는 얇은 클라이언트로 남음.

### v1.5.0 — 로그인 화면 + 관리자 페이지 (진행 중, 실기기 검증은 내일)
프론트엔드에 로그인 게이트와 Electron `safeStorage` 기반 토큰 영속화를 붙이고, 계정 관리용 관리자 페이지를 추가.
- [x] `LoginView.jsx` — 아이디/비밀번호 로그인 화면, 앱 첫 진입 화면으로 게이팅
- [x] Electron `safeStorage`로 토큰 암호화 저장 (`main.js`의 `save-token`/`load-token`/`clear-token` IPC, `preload.js` 브릿지)
- [x] `App.jsx` — 저장된 토큰 자동 로드, `/start`·`/resume`·`/save` 요청에 `Authorization` 헤더 부착, 401 시 자동 로그아웃
- [x] 사이드바에 로그아웃 버튼 추가
- [x] **관리자 페이지(`AdminView.jsx`)** — 계정 목록/생성/월 사용 한도 조정/활성-비활성 토글
- [x] 로컬 백엔드에 `/me`, `/admin/accounts` 프록시 라우트 추가
- [x] 중앙 서버(`voxscript_auth_server`)에 `require_admin` 의존성 + 계정 CRUD 엔드포인트 추가
- [x] **라우트 등록 순서 버그 수정** — `/me`/`/admin/*` 라우트가 `if __name__ == "__main__":` 아래(즉 `uvicorn.run()` 블로킹 호출 이후)에 있어서 실제로 등록된 적이 없던 문제 발견 → 파일 상단 라우트 정의 구간으로 이동
- [x] 프로젝트/임시/출력 파일 저장 위치를 `~/Downloads/VOXScript` → Electron `userData` 경로(`%APPDATA%\VOXScript`)로 이전 — 설치 폴더가 재설치 시 갈아엎어지면서 데이터가 유실되는 문제 방지, 탐색 용이성도 개선 (`VOXSCRIPT_DATA_DIR` env var로 Electron → 백엔드 전달, 미설정 시 기존 Downloads 경로로 폴백)
- [x] **"폴더 열기" 버튼 무반응 버그 수정** — `ProjectStatus`/`VoxProject`에 `files` 필드가 아예 없어서 프론트가 항상 빈 값만 받고 있었음 → 필드 추가, `_run_stage3`에서 저장된 파일 경로를 채워 넣도록 수정
- [x] `resources/bin/`(ffmpeg·ffprobe·yt-dlp·deno) 바이너리 자동 다운로드 스크립트(`scripts/fetch-binaries.js`) 추가 — 없는 바이너리만 GitHub 릴리즈에서 받아오고 `yarn package`에 자동 연결, 매번 손으로 받아 넣던 작업 제거
- [x] `SegmentData.translated`/`.original`이 `None`일 수 있는 지점에서 `.strip()`을 직접 호출하던 부분에 방어 코드 추가 (`formatter.py`)
- [x] Electron 창 타이틀이 Vite 기본값("frontend")으로 표시되던 것 수정
- [x] **관리자 API 라우트 등록 순서 버그 수정** — `/me`/`/admin/*` 라우트가 `if __name__ == "__main__":` 아래(즉 `uvicorn.run()` 블로킹 호출 이후)에 있어서 실제로 등록된 적이 없던 문제 발견 → 파일 상단 라우트 정의 구간으로 이동
- [x] 실기기 인스톨러 테스트 중 **YouTube 다운로드 403 재발** 확인 — `resources/bin/deno.exe` 미배치가 원인 (자동 다운로드 스크립트로 해결). **AI 처리 키(`OPENAI_API_KEY` 등) 미설정 시 로컬 Whisper 폴백을 시도하다 배포판에서 제외된 모듈이라 크래시**하는 것도 확인 — 현재는 설치 후 `.env` 수동 배치가 필요한 상태 (이 키들은 아직 중앙 서버로 이관 전)

> **다음 방향 결정 필요**: AI 처리 키(OpenAI/Gemini/DeepL)가 로컬 `.env`에 있어야 하는 구조라 "설치만 하면 바로 되는" 배포가 안 됨. 데스크탑 앱을 유지하며 AI 프록시만 중앙화할지, 웹 서비스(Railway 풀배포)로 전환할지 논의 중 — 제3자 배포가 목표라 사용량 통제·설치 마찰 면에서 후자 쪽에 무게가 실림. 다음 세션에서 웹 전환 설계 착수 예정.
---

## 성능 참고

| 영상 길이 | Whisper API | Gemini 전처리 | 총 소요 |
|---|---|---|---|
| 5분 | ~5초 | ~1분 | ~1.5분 |
| 30분 | ~30초 | ~6분 | ~8분 |
| 1시간 | ~1분 | ~12분 | ~18분 |

> Whisper API 기준 (24MB 이하 단일 호출), 24MB 초과 시 자동으로 20분 단위 청크 분할 처리. 화자 구분 포함 시 +3~5분.

---

## 알려진 이슈

- **YouTube 다운로드**: 비공개/연령제한 영상은 yt-dlp가 쿠키 없이 처리 못 함 (JS 런타임 요구사항은 `deno` 연동으로 해결됨, 이건 별개의 제약).
- **Google Drive 인증**: 개발자 본인의 OAuth 클라이언트 기준으로 동작하므로, 다른 PC에서 처음 실행하면 브라우저 로그인이 한 번 필요함. PyInstaller frozen 빌드에서 `credentials.json`/`token.json` 경로를 `sys.executable` 기준으로 잡도록 수정했고, 실제 패키징된 exe로 Drive 다운로드까지 실기기 검증 완료
- **로컬 Whisper(CUDA) 폴백**: 배포용 패키징에서는 의도적으로 제외(용량 문제) — GPU가 있는 PC에서 dev 모드(`python main.py`)로 실행할 때만 사용 가능, `OPENAI_API_KEY`가 없을 때 자동으로 이 경로를 탐. 패키징 빌드는 `whisper` 모듈 자체가 빠져있어서 이 경로를 타면 `ModuleNotFoundError`로 즉시 드러남 (의도된 동작)
- **`.env`/`credentials.json`/`token.json`은 빌드에 안 포함됨**: 셋 다 gitignore된 개인 파일이라 PyInstaller/electron-builder 산출물에 자동으로 안 들어감. 패키징 후 설치된 앱의 `resources/backend/`에 직접 복사해 넣어야 함 (재설치할 때마다 반복 필요 — 테스트 단계에서 반복 작업 줄이려고 로컬용 복사 스크립트를 따로 만들어 씀, 저장소에는 포함 안 함)

---

## 관련 프로젝트

| 프로젝트 | 설명 | 스택 |
|---|---|---|
| [miniERP](https://github.com/TerryBlackhoodWoo/miniErp) | 면세점 도메인 기반 미니 ERP | Java, Spring Boot, PostgreSQL, React |
| [SOHOBI](https://github.com/TerryBlackhoodWoo/sohobi) | 상권 분석 플랫폼 | Python, FastAPI, React |

---

## 향후 확장 계획
- electron-updater 기반 자동 업데이트
- `.vox` 프로젝트 파일 다중 선택/일괄 삭제 UI
- 화자 라벨링 결과를 다음 프로젝트에 학습 데이터로 재사용 (반복 출연자 자동 인식)
- SRT 타임스탬프 미세 조정 UI (현재는 텍스트 편집만 지원)