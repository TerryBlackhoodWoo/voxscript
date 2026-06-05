# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 도구

**Whisper API(STT) + DeepL(번역) + Gemini(전처리/화자구분/요약)** 파이프라인으로  
YouTube / Google Drive / 로컬 파일을 자동으로 번역 스크립트로 변환합니다.

---

## 주요 기능

- **다국어 STT** — OpenAI Whisper API (자동) / 로컬 Whisper CUDA (폴백), 언어 자동 감지
- **중복 제거** — Gemini가 Whisper 슬라이딩 윈도우 중복 세그먼트 병렬 정리
- **DeepL 번역** — 월 500,000자 무료 / 한국어 소스는 번역 자동 스킵
- **화자 구분** — Gemini 텍스트 분석 기반, 자동 감지 or 이름 직접 지정 (3명 이상 지원)
- **다양한 출력 포맷** — TXT / SRT / Excel (화자별 색상, 한국어 시 Translation 컬럼 생략)
- **원본 파일명 기반 폴더 생성** — Google Drive / 로컬 / YouTube 원본명 그대로 저장
- **Google Drive 연동** — 폴더 링크로 음원 직접 다운로드 (OAuth)
- **Electron 데스크탑 앱** — React UI + FastAPI 백엔드 통합

---

## 프로젝트 구조

```
VOXScript/
├── backend/
│   ├── pipeline.py       ← CLI 진입점 (컨트롤러)
│   ├── main.py           ← FastAPI 서버 (Electron 백엔드용)
│   ├── cleaner.py        ← Gemini 전처리 (중복제거 + 문단묶기, 병렬처리)
│   ├── requirements.txt
│   └── DAO/
│       ├── downloader.py   ← YouTube / Google Drive / 로컬 파일 + 원본파일명 반환
│       ├── transcriber.py  ← Whisper API / 로컬 CUDA 자동 선택 + 청크 분할
│       ├── translator.py   ← DeepL 번역 (한국어 스킵)
│       ├── diarizer.py     ← Gemini 화자 구분 (자동/수동, chunk_size=50, 재시도)
│       └── formatter.py    ← 파일 저장 (TXT/SRT/Excel) + Gemini 요약
├── electron/
│   ├── main.js           ← Electron 메인 (FastAPI 백그라운드 실행)
│   └── preload.js        ← IPC 브릿지
├── frontend/             ← React + Vite UI (별도 레포: voxscript_frontend)
├── package.json          ← Electron 패키징 설정
└── .env.example
```

---

## 환경 요구사항

- Python 3.11
- Node.js 18+
- NVIDIA GPU (CUDA 12.1) — RTX 3060 이상 권장 (로컬 Whisper 사용 시)
- ffmpeg (PATH 등록 필요)

---

## 빠른 시작

### CLI 모드

```bash
cd backend
pip install -r requirements.txt
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

cp .env.example .env
# .env 파일 열어서 키 입력

# Google Drive 폴더
python pipeline.py "https://drive.google.com/drive/folders/FOLDER_ID" --lang en --format all

# 로컬 파일
python pipeline.py "./video.mp4" --lang ja --format all

# 화자 구분 자동
python pipeline.py "URL" --lang en --format all --diarize

# 화자 이름 직접 지정
python pipeline.py "URL" --lang en --format all --diarize --speakers 진행자 젠슨황

# 화자 3명
python pipeline.py "URL" --lang en --format all --diarize --speakers 진행자 게스트1 게스트2
```

### Electron 앱 모드

```bash
# 루트에서
npm install

# 프로덕션 빌드 후 실행
npm run build
npm run electron
```

---

## 전체 CLI 옵션

```
positional arguments:
  source                YouTube URL / Google Drive URL / 로컬 파일 경로

options:
  --lang                원본 언어 (auto/es/en/ko/ja/zh/fr/de/pt, 기본: auto)
  --target              번역 타겟 (KO/EN-US/JA 등, 기본: KO)
  --format              출력 포맷 (기본: txt_bilingual,srt_bilingual)
  --model               Whisper 모델 (tiny/base/small/medium/large, 기본: medium)
  --import-dir          음원 임시 저장 폴더
  --export-dir          결과물 저장 폴더
  --diarize             화자 구분 활성화 (Gemini 텍스트 분석)
  --speakers            화자 이름 목록 (예: --speakers 진행자 젠슨황 게스트)
  --no-summary          Gemini 요약 생략
```

## 출력 포맷

| 옵션 | 설명 |
|---|---|
| `txt` | 번역만 텍스트 |
| `txt_bilingual` | 타임코드 + 원문 + 번역 텍스트 |
| `srt` | 번역 SRT 자막 |
| `srt_bilingual` | 원문/번역 병기 SRT |
| `excel` | 타임코드/화자/원문/번역 Excel (화자별 색상, 한국어 시 번역 컬럼 생략) |
| `all` | 전부 저장 |

---

## API 키 설정

| 키 | 발급처 | 비용 |
|---|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com | $0.006/분 (Whisper API) |
| `GEMINI_API_KEY` | https://aistudio.google.com/ | 유료 (Google Cloud Console) |
| `DEEPL_API_KEY` | https://www.deepl.com/ko/pro-api | 월 500,000자 무료 |

> `OPENAI_API_KEY` 없으면 로컬 Whisper CUDA 자동 사용  
> Google Drive 연동 시 `credentials.json` 별도 필요

---

## 파이프라인 흐름

```
입력 (YouTube URL / Google Drive / 로컬 파일)
    ↓
[1] 음원 추출 + 원본 파일명 추출 (yt-dlp / Google Drive API / ffmpeg, 64kbps)
    ↓
[2] Whisper STT
    ├── 24MB 이하 → OpenAI Whisper API (~10초/30분)
    └── 24MB 초과 → 로컬 Whisper CUDA 폴백
    ↓
[3] Gemini 전처리 (중복 제거 + 문단 묶기, chunk_size=150, 병렬처리)
    ↓
[4] DeepL 번역 (한국어 소스면 스킵)
    ↓
[4.5] Gemini 화자 구분 (선택, 자동/수동, chunk_size=50, 재시도)
    ↓
[5] 포맷 저장 + Gemini 요약
    ↓
출력 폴더 (원본 파일명 기반 자동 생성)
```

---

## 성능 참고

| 영상 길이 | Whisper API | Gemini 전처리 | 번역+요약 | 총 소요 |
|---|---|---|---|---|
| 5분 | ~5초 | ~1분 | ~20초 | ~1.5분 |
| 30분 | ~30초 | ~6분 | ~1분 | ~8분 |
| 1시간 | ~1분 | ~12분 | ~5분 | ~18분 |

> Whisper API 기준 (24MB 이하)  
> 24MB 초과 시 RTX 4050 Laptop GPU 로컬 폴백  
> 화자 구분(`--diarize`) 포함 시 +3~5분 추가

---

## Google Drive 연동 설정

1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 생성
2. Google Drive API 활성화
3. OAuth 2.0 클라이언트 ID 발급 (데스크탑 앱)
4. `credentials.json` 다운로드 → `backend/` 폴더에 저장
5. 첫 실행 시 브라우저 인증 → `token.json` 자동 생성

> ⚠️ `credentials.json` / `token.json` / `.env` 는 `.gitignore`에 포함 필수

---

## 개발 로드맵

- [x] v0.1.0: CLI 파이프라인
  - [x] YouTube / Google Drive / 로컬 파일 지원
  - [x] Whisper STT (CUDA)
  - [x] Gemini 전처리 (중복제거 + 문단묶기)
  - [x] DeepL 번역
  - [x] Gemini 화자 구분 (텍스트 기반, 다중 화자)
  - [x] 다양한 출력 포맷 (TXT/SRT/Excel 화자별 색상)
  - [x] Gemini 요약 + 자동 제목
- [x] v0.2.0: Electron 데스크탑 앱
  - [x] React 3패널 UI (사이드바/스크립트뷰/설정패널)
  - [x] FastAPI 연동 (처리 시작 + 진행상태 polling)
  - [x] 화자 동적 추가/삭제 UI
  - [x] 완료 작업 자동 표시
- [x] v0.3.0: 성능 개선 + UI 개선
  - [x] OpenAI Whisper API 연동 (자동 선택, 로컬 폴백)
  - [x] Gemini 전처리 병렬 처리
  - [x] 화자 구분 자동/수동 모드
  - [x] 한국어 소스 번역 스킵
  - [x] 한국어 Excel Translation 컬럼 생략
  - [x] 원본 파일명 기반 폴더 생성
  - [x] 처리 중 단계별 로그 + 소요시간 표시
  - [x] 로컬 파일 선택 버튼
- [ ] v0.3.1: 안정화
  - [ ] 백엔드 로그 영어 통일
  - [ ] .exe 패키징
- [ ] v0.4.0: CSS + 웹 버전
  - [ ] CSS 다듬기
  - [ ] Vercel + Railway 웹 배포