# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 도구

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/Electron-32-47848F)](https://www.electronjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.4.0-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-Vite-61dafb)](https://vitejs.dev/)

---

## 프로젝트 소개

> 🖥️ **배포 형태**: Windows 데스크탑 앱 (NSIS 인스톨러, PyInstaller로 백엔드까지 단일 실행파일화 — 사용자 PC에 Python 설치 불필요)

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
# 1) ffmpeg.exe / ffprobe.exe / yt-dlp.exe를 resources/bin/ 에 받아넣기
#    - ffmpeg: https://github.com/BtbN/FFmpeg-Builds/releases
#    - yt-dlp: https://github.com/yt-dlp/yt-dlp/releases

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

> `/start`, `/resume`, `/save`는 모두 백그라운드 스레드에서 실행되고, 프론트엔드는 `/status/{project_id}`를 폴링해서 진행률·로그를 받아오는 구조입니다. Electron `main.js`의 IPC 핸들러(`startPipeline`, `resumePipeline`, `saveOutput`, `getStatus`, `getProjects`, `loadProject`, `getLanguages`, `getFormats`)가 위 엔드포인트들과 1:1로 매핑되어 있습니다.

---

## 프로젝트 구조

```
VOXScript/
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
├── resources/
│   └── bin/                     ← 배포용 바이너리 (gitignore, 빌드 전 별도 다운로드)
│       ├── ffmpeg.exe
│       ├── ffprobe.exe
│       └── yt-dlp.exe
├── frontend/                    ← React + Vite UI (별도 레포: voxscript_frontend)
├── backend-dist/                ← PyInstaller 빌드 출력 (gitignore, `yarn build:backend`로 생성)
├── package.json
└── .env.example
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

### v1.1.0 — 오프라인 배포 패키징 (진행 중)
- [x] ffmpeg/ffprobe/yt-dlp 하드코딩 호출 제거 → `DAO/bin_paths.py`로 경로 해석 일원화
- [x] PyInstaller 백엔드 빌드 스펙 작성 + 실제 빌드/구동 검증 (`google.genai`, `googleapiclient` hidden import 포함)
- [x] `googleapiclient`가 기본으로 끌고 오는 discovery 문서 정리 (Drive v3만 남기고 나머지 제거, 97MB → 1MB)
- [x] **`.vox` 프로젝트 저장 경로 불일치 버그 수정** — `save_project()`는 `{project_dir}/{이름}_{project_id}.vox` 형태로 평평하게 저장하는데, `main.py`의 `/status`·`/load`는 `{project_id}/project.vox`라는 존재하지 않는 하위 폴더 구조를 찾고 있어서 서버 재시작 후 "프로젝트 이어하기"가 항상 실패하던 문제 발견. `find_project_file()` 헬퍼를 추가해 동일한 flat glob 패턴(`*_{project_id}.vox`)으로 통일
- [x] **Electron ↔ 백엔드 API 스키마 불일치 수정** — `main.js`가 실제로는 존재하지 않는 `/process` 엔드포인트를 호출하고 있었고 필드명(`language`/`formats` 등)도 실제 스키마와 달랐음. `/resume`·`/save`·`/projects`·`/load`에 대응하는 IPC 핸들러 자체가 없어서 5단계 파이프라인과 전혀 연동이 안 되는 상태였던 것을 발견 → `/start`·`/resume/{id}`·`/save/{id}`·`/status/{id}`·`/projects`·`/load/{id}`·`/languages`·`/formats`에 맞춰 IPC 핸들러 전면 재작성, `preload.js`에 노출
- [x] **PyInstaller frozen 빌드의 OAuth 자격증명 경로 버그 수정** — `downloader.py`의 `CREDENTIALS_PATH`가 `Path(__file__).parent.parent` 기준이라 onedir 빌드에서 `_internal/` 폴더 안쪽을 가리키게 됨(exe와 한 단계 어긋남) → `sys.frozen` 여부에 따라 `sys.executable` 기준으로 분기하도록 수정
- [x] `/save` 엔드포인트에 `stage != SAVING`이면 400 반환하는 방어 코드 추가, 백엔드 기동 실패 시 `dialog.showErrorBox`로 사용자 안내 추가
- [x] **`.gitignore` 정비** — 패키징 빌드 산출물(`dist/`, `backend-dist/`) 경유로 `credentials.json`/`token.json`이 함께 묶여 나가던 것을 확인 → 해당 OAuth 클라이언트 재발급 후 `.gitignore`에 `dist/`, `backend-dist/`, `credentials.json`, `token.json`, `.env` 전부 등록해 재발 방지
- [ ] ffmpeg/ffprobe/yt-dlp 바이너리 `resources/bin/`에 실제 배치
- [ ] Windows 환경에서 `yarn package` 풀 빌드 + 실기기 동작 검증 (특히 credentials.json 경로 수정, Google Drive 인증 흐름까지 포함)
- [ ] `downloader.py` docstring 정리 (YouTube 관련 stale 코멘트 — 중복 블록만 제거됐고 내용 자체는 아직 미수정)
- [ ] PyInstaller 콘솔창 숨기기 (`console=False`)

> BOM/GWP 같은 부가 기능 없이, 핵심 파이프라인의 "진짜 배포 가능한 상태" 만드는 게 v1.1.0의 목표.

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

- **YouTube 다운로드**: 비공개/연령제한 영상은 yt-dlp가 쿠키 없이 처리 못 함. `downloader.py` 상단 docstring에 "YouTube removed"라고 적혀 있는데 실제로는 yt-dlp 기반으로 살아있는 상태라 문서와 코드가 불일치 — 내용 자체는 아직 미수정
- **Google Drive 인증**: 개발자 본인의 OAuth 클라이언트 기준으로 동작하므로, 다른 PC에서 처음 실행하면 브라우저 로그인이 한 번 필요함. PyInstaller frozen 빌드에서 `credentials.json`/`token.json` 경로를 `sys.executable` 기준으로 잡도록 수정했으나, 실제 패키징된 exe로 인증 흐름까지 풀 테스트는 아직 안 함
- **로컬 Whisper(CUDA) 폴백**: 배포용 패키징에서는 의도적으로 제외(용량 문제) — GPU가 있는 PC에서 dev 모드(`python main.py`)로 실행할 때만 사용 가능, `OPENAI_API_KEY`가 없을 때 자동으로 이 경로를 탐
- **PyInstaller 빌드 콘솔창**: 현재 `voxscript-backend.spec`이 `console=True`로 디버깅용 콘솔을 띄움. 안정화되면 `False`로 바꿔서 숨길 수 있음

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