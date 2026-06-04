# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 CLI 도구

**Whisper(로컬 STT) + DeepL(번역) + Gemini(전처리/화자구분/요약)** 파이프라인으로  
YouTube / Google Drive / 로컬 파일을 자동으로 번역 스크립트로 변환합니다.

---

## 주요 기능

- **다국어 STT** — Whisper medium (CUDA), 언어 자동 감지 또는 수동 지정
- **중복 제거** — Gemini가 Whisper 슬라이딩 윈도우 중복 세그먼트 정리
- **DeepL 번역** — 월 500,000자 무료 (한국어/영어/일본어 등)
- **화자 구분** — Gemini 텍스트 분석 기반 자동 라벨링 (이름 직접 지정 가능)
- **다양한 출력 포맷** — TXT / SRT / Excel (화자별 색상 구분)
- **자동 제목 추출** — Gemini가 내용 기반으로 파일명/폴더명 자동 생성
- **Google Drive 연동** — 폴더 링크로 음원 직접 다운로드 (OAuth)

---

## 프로젝트 구조

```
VOXScript/
├── backend/
│   ├── pipeline.py       ← CLI 진입점 (컨트롤러)
│   ├── main.py           ← FastAPI 서버 (Electron 백엔드용)
│   ├── cleaner.py        ← Gemini 전처리 (중복제거 + 문단묶기)
│   ├── requirements.txt
│   └── DAO/
│       ├── __init__.py
│       ├── downloader.py   ← YouTube / Google Drive / 로컬 파일
│       ├── transcriber.py  ← Whisper STT (CUDA)
│       ├── translator.py   ← DeepL 번역
│       ├── diarizer.py     ← Gemini 화자 구분
│       └── formatter.py    ← 파일 저장 (TXT/SRT/Excel) + Gemini 요약
├── electron/
│   ├── main.js           ← Electron 메인 (FastAPI 백그라운드 실행)
│   └── preload.js        ← IPC 브릿지
└── .env.example
```

---

## 환경 요구사항

- Python 3.11
- NVIDIA GPU (CUDA 12.1) — RTX 3060 이상 권장
- ffmpeg (PATH 등록 필요)

---

## 빠른 시작

### 1. 의존성 설치

```bash
cd backend
pip install -r requirements.txt

# PyTorch CUDA 버전 (GPU 사용 필수)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# ffmpeg 설치 (Windows)
# https://ffmpeg.org/download.html 다운로드 후 PATH 추가
```

### 2. API 키 설정

```bash
cp .env.example .env
# .env 파일 열어서 키 입력
```

| 키 | 발급처 | 비용 |
|---|---|---|
| `DEEPL_API_KEY` | https://www.deepl.com/ko/pro-api | 월 500,000자 무료 |
| `GEMINI_API_KEY` | https://aistudio.google.com/ | 무료 (카드 불필요) |

> Google Drive 연동 시 `credentials.json` 별도 필요 (하단 참고)

### 3. 실행

```bash
cd backend

# YouTube
python pipeline.py "https://www.youtube.com/watch?v=VIDEO_ID" --lang en --format all

# Google Drive 폴더
python pipeline.py "https://drive.google.com/drive/folders/FOLDER_ID" --lang ja --format all

# 로컬 파일
python pipeline.py "./video.mp4" --lang es --format all

# 화자 구분 (기본: 인터뷰어/인터뷰이)
python pipeline.py "URL" --lang en --format all --diarize

# 화자 이름 직접 지정
python pipeline.py "URL" --lang en --format all --diarize --speaker1 "진행자" --speaker2 "젠슨황"
```

---

## 전체 옵션

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
  --speaker1            화자1 이름 (기본: 진행자,진행자1)
  --speaker2            화자2 이름 (기본: 젠승황,진행자2)
  --no-summary          Gemini 요약 생략
```

## 출력 포맷

| 옵션 | 설명 |
|---|---|
| `txt` | 번역만 텍스트 |
| `txt_bilingual` | 타임코드 + 원문 + 번역 텍스트 |
| `srt` | 번역 SRT 자막 |
| `srt_bilingual` | 원문/번역 병기 SRT |
| `excel` | 타임코드/화자/원문/번역 Excel (화자별 색상) |
| `all` | 전부 저장 |

복수 선택: `--format srt_bilingual,excel`

---

## 파이프라인 흐름

```
입력 (YouTube URL / Google Drive / 로컬 파일)
    ↓
[1] 음원 추출 (yt-dlp / Google Drive API / ffmpeg)
    ↓
[2] Whisper STT (로컬 CUDA, 언어 자동감지)
    ↓
[3] Gemini 전처리 (중복 제거 + 문단 묶기, chunk_size=150)
    ↓
[4] DeepL 번역
    ↓
[4.5] Gemini 화자 구분 (선택, --diarize)
    ↓
[5] 포맷 저장 + Gemini 요약 + 자동 제목 추출
    ↓
출력 폴더 (제목 기반 자동 생성)
```

---

## 성능 참고

| 영상 길이 | Whisper | Gemini 전처리 | 번역+요약 | 총 소요 |
|---|---|---|---|---|
| 5분 | ~1분 | ~1분 | ~20초 | ~2분 |
| 30분 | ~6분 | ~6분 | ~1분 | ~13분 |
| 1시간 | ~12분 | ~12분 | ~5분 | ~29분 |

> RTX 4050 Laptop GPU 기준 (실측, chunk_size=150)  
> 화자 구분(`--diarize`) 포함 시 +4~5분 추가

---

## Google Drive 연동 설정

1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 생성
2. Google Drive API 활성화
3. OAuth 2.0 클라이언트 ID 발급 (데스크톱 앱)
4. `credentials.json` 다운로드 → `backend/` 폴더에 저장
5. 첫 실행 시 브라우저 인증 → `token.json` 자동 생성

> ⚠️ `credentials.json` / `token.json` / `.env` 는 `.gitignore`에 포함 필수

---

## 개발 로드맵

- [x] Phase 1: CLI 파이프라인
  - [x] YouTube / Google Drive / 로컬 파일 지원
  - [x] Whisper STT (CUDA)
  - [x] Gemini 전처리 (중복제거 + 문단묶기)
  - [x] DeepL 번역
  - [x] Gemini 화자 구분 (텍스트 기반, 이름 직접 지정)
  - [x] 다양한 출력 포맷 (TXT/SRT/Excel 화자별 색상)
  - [x] Gemini 요약 + 자동 제목
- [ ] Phase 2: React + Electron UI
  - [ ] 링크/파일 입력 UI
  - [ ] 실시간 진행 상태 표시
  - [ ] 출력 폴더/화자 설정
- [ ] Phase 3: 패키징 (.exe 배포)
- [ ] v0.2: Groq Whisper API 연동 (속도 개선)