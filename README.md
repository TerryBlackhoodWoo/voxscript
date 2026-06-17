# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 도구

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/Electron-32-47848F)](https://www.electronjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.4.0-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-Vite-61dafb)](https://vitejs.dev/)

**Whisper API(STT) + DeepL(번역) + Gemini(전처리/화자구분/요약)** 파이프라인으로
YouTube / Google Drive / 로컬 파일을 자동으로 번역 스크립트로 변환하는 Electron 데스크탑 앱입니다.

---

## 프로젝트 소개

### 기획 배경
- 실제 사용자(방송 작가)가 스페인어 다큐멘터리 인터뷰 영상을 매번 외주로 번역·정리하던 비효율을 직접 겪고 시작한 프로젝트
- STT 결과는 항상 노이즈(중복 발화, 어색한 줄바꿈)가 섞여 있어 "받아쓰기"와 "쓸 수 있는 스크립트" 사이 간극이 큼 → Gemini로 전처리 단계를 분리해서 해결
- 화자 구분을 영상/음성 기반(pyannote 등)이 아니라 **번역된 텍스트의 대화 패턴**으로 추론하는 방식 채택 — 질문/응답 길이, 반응 패턴 등으로 인터뷰어·인터뷰이를 구분
- 1시간 단위 STT를 한 번에 돌리면 중간에 실패 시 처음부터 다시 해야 하는 문제 → 단계별 파이프라인(다운로드 → STT/전처리 → **유저 라벨링 대기** → 화자 fill/번역 → 저장)으로 분리, `.vox` 프로젝트 파일로 중간 상태 저장/이어하기 지원

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

---

## 파이프라인 흐름 (v0.6.0)

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
| POST | `/save/{project_id}` | 최종 포맷 변환 + 파일 저장 |
| GET | `/load/{project_id}` | 저장된 `.vox` 프로젝트 이어하기 |

> `/start`, `/resume`, `/save`는 모두 백그라운드 스레드에서 실행되고, 프론트엔드는 `/status/{project_id}`를 폴링해서 진행률·로그를 받아오는 구조입니다.

---

## 환경 설정

| 키 | 발급처 | 비용 | 용도 |
|---|---|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com | $0.006/분 | Whisper STT |
| `GEMINI_API_KEY` | https://console.cloud.google.com | 유료 | 전처리/화자구분/요약 |
| `DEEPL_API_KEY` | https://www.deepl.com/ko/pro-api | 월 500,000자 무료 | 번역 |

Google Drive 다운로드 기능은 API 키가 아니라 **OAuth 2.0 흐름**을 씁니다. Google Cloud Console에서 OAuth 클라이언트(Desktop App 타입)를 만들어 `backend/credentials.json`으로 저장하면, 최초 실행 시 브라우저가 열려 로그인 → `backend/token.json`이 자동 생성됩니다. 두 파일 모두 개인 인증 정보이므로 절대 커밋하지 마세요.

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

- **YouTube 다운로드**: 비공개/연령제한 영상은 yt-dlp가 쿠키 없이 처리 못 함. `downloader.py` 상단 docstring에 "YouTube removed"라고 적혀 있는데 실제로는 yt-dlp 기반으로 살아있는 상태라 문서와 코드가 불일치 — docstring 정리 필요.
- **Google Drive 인증**: 개발자 본인의 OAuth 클라이언트 기준으로 동작하므로, 다른 PC에서 처음 실행하면 브라우저 로그인이 한 번 필요함.
- **로컬 Whisper(CUDA) 폴백**: 배포용 패키징에서는 의도적으로 제외(용량 문제) — GPU가 있는 PC에서 dev 모드(`python main.py`)로 실행할 때만 사용 가능, `OPENAI_API_KEY`가 없을 때 자동으로 이 경로를 탐.
- **PyInstaller 빌드 콘솔창**: 현재 `voxscript-backend.spec`이 `console=True`로 디버깅용 콘솔을 띄움. 안정화되면 `False`로 바꿔서 숨길 수 있음.

---

## 관련 프로젝트

| 프로젝트 | 설명 | 스택 |
|---|---|---|
| [miniERP](https://github.com/TerryBlackhoodWoo/miniErp) | 면세점 도메인 기반 미니 ERP | Java, Spring Boot, PostgreSQL, React |
| [SOHOBI](https://github.com/TerryBlackhoodWoo/sohobi) | 상권 분석 플랫폼 | Python, FastAPI, React |

---

## 개발 로드맵

- [x] v0.1.0: CLI 파이프라인
- [x] v0.2.0: Electron 데스크탑 앱
- [x] v0.3.0: Whisper API + Gemini 병렬처리 + 한국어 최적화
- [x] v0.4.0: 단계별 파이프라인 + 화자 라벨링 UI + 프로젝트 파일
- [x] v0.5.0: UI 최적화
  - [x] 중앙 뷰 프로젝트 요약 표시
  - [x] 파일 목록 + 열기 버튼
  - [x] Inter + Noto Sans KR 폰트
- [x] v0.6.0: 스크립트 편집 UI
  - [x] 텍스트 인라인 편집
  - [x] 행 분리 / 병합
  - [x] 화자 드롭다운 (기본값 미지정)
- [x] v1.0.0: 배포 + 자동 업데이트
  - [x] 앱 아이콘
  - [x] .exe 패키징 (electron-builder)
  - [ ] 자동 업데이트 (electron-updater)
- [ ] v1.1.0: 오프라인 배포 패키징 (진행 중)
  - [x] ffmpeg/ffprobe/yt-dlp 하드코딩 호출 제거 → `DAO/bin_paths.py`로 경로 해석 일원화
  - [x] PyInstaller 백엔드 빌드 스펙 작성 + 실제 빌드/구동 검증 (google.genai, googleapiclient hidden import 포함)
  - [x] googleapiclient discovery_cache 불필요 API 문서 제거 (97MB → 1MB 수준)
  - [ ] ffmpeg/ffprobe/yt-dlp 바이너리 `resources/bin/`에 실제 배치
  - [ ] Windows 환경에서 `yarn package` 풀 빌드 + 실기기 동작 검증
  - [ ] `downloader.py` docstring 정리 (YouTube 관련 stale 코멘트)
  - [ ] PyInstaller 콘솔창 숨기기 (`console=False`)

> BOM/GWP 같은 부가 기능 없이, 핵심 파이프라인의 "진짜 배포 가능한 상태" 만드는 게 v1.1.0의 목표.

---

## 향후 확장 계획
- electron-updater 기반 자동 업데이트
- `.vox` 프로젝트 파일 다중 선택/일괄 삭제 UI
- 화자 라벨링 결과를 다음 프로젝트에 학습 데이터로 재사용 (반복 출연자 자동 인식)
- SRT 타임스탬프 미세 조정 UI (현재는 텍스트 편집만 지원)