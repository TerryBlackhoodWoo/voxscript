# VOXScript

> 음원/영상 링크 → STT → 번역 → 정리본 자동 생성 도구

**Whisper API(STT) + DeepL(번역) + Gemini(전처리/화자구분/요약)** 파이프라인으로  
YouTube / Google Drive / 로컬 파일을 자동으로 번역 스크립트로 변환합니다.

---

## 주요 기능

- **다국어 STT** — OpenAI Whisper API (자동) / 로컬 Whisper CUDA (폴백)
- **중복 제거** — Gemini 병렬 전처리 (Q&A 구조 보존, 화자 전환 시 분리 유지)
- **DeepL 번역** — 한국어 소스 자동 스킵
- **단계별 화자 라벨링** — 처리 중 일시 정지 → 유저 직접 라벨링 → AI 자동 fill
- **프로젝트 파일 저장** — `.vox` 형식으로 중간 저장, 이어하기 가능
- **다양한 출력 포맷** — TXT / SRT / Excel (화자별 색상, 한국어 Translation 컬럼 생략)
- **원본 파일명 기반 폴더 생성** — YouTube 제목 / Google Drive / 로컬 파일명
- **Electron 데스크탑 앱** — React UI + FastAPI 백엔드 통합

---

## 프로젝트 구조

```
VOXScript/
├── backend/
│   ├── pipeline.py         ← CLI 진입점
│   ├── main.py             ← FastAPI 서버 (v0.4.0 단계별 파이프라인)
│   ├── project_schema.py   ← VoxProject 프로젝트 파일 구조
│   ├── cleaner.py          ← Gemini 전처리 (병렬처리, Q&A 구조 보존)
│   ├── requirements.txt
│   └── DAO/
│       ├── downloader.py   ← YouTube 제목 추출 / Google Drive / 로컬
│       ├── transcriber.py  ← Whisper API / 로컬 CUDA 자동 선택
│       ├── translator.py   ← DeepL 번역 (한국어 스킵)
│       ├── diarizer.py     ← Gemini 화자 구분 (유저 지정 우선)
│       └── formatter.py    ← 파일 저장 + Gemini 요약
├── electron/
│   ├── main.js
│   └── preload.js
├── frontend/               ← React + Vite UI (별도 레포: voxscript_frontend)
├── package.json
└── .env.example
```

---

## 환경 요구사항

- Python 3.11
- Node.js 18+
- NVIDIA GPU (CUDA 12.1) — 로컬 Whisper 사용 시
- ffmpeg (PATH 등록 필요)

---

## 빠른 시작

### Electron 앱 모드

```bash
npm install
npm run build
npm run electron
```

### CLI 모드

```bash
cd backend
pip install -r requirements.txt

# Google Drive
python pipeline.py "https://drive.google.com/drive/folders/FOLDER_ID" --lang en --format all

# 로컬 파일
python pipeline.py "./video.mp4" --lang ja --format all

# 화자 구분
python pipeline.py "URL" --lang en --format all --diarize --speakers 진행자 게스트
```

---

## 파이프라인 흐름 (v0.4.0)

```
입력 (YouTube / Google Drive / 로컬)
    ↓
[1단계] 다운로드 → Whisper STT → Gemini 전처리
    ↓
[2단계] ⏸ 화자 라벨링 (유저 개입)
         - 앞 30개 세그먼트 표시
         - 화자 이름 직접 입력/수정
         - 확인 or 스킵 (AI 자동)
    ↓
[3단계] 나머지 화자 자동 fill (Gemini)
    ↓
[4단계] 번역 (한국어 소스면 스킵)
    ↓
[5단계] 저장 경로 선택 → 파일 저장
    ↓
프로젝트 폴더 (원본 파일명 기반)
```

---

## 프로젝트 파일 (.vox)

```
~/Downloads/VOXScript/projects/
└── 나성범_인터뷰/
    ├── project.vox    ← 단계별 상태 저장 (이어하기 가능)
    └── output/        ← 완성된 파일들
```

단계 목록: `init → downloading → transcribing → cleaning → labeling → diarizing → translating → saving → done`

---

## API 키 설정

| 키 | 발급처 | 비용 |
|---|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com | $0.006/분 |
| `GEMINI_API_KEY` | https://console.cloud.google.com | 유료 |
| `DEEPL_API_KEY` | https://www.deepl.com/ko/pro-api | 월 500,000자 무료 |

---

## 성능 참고

| 영상 길이 | Whisper API | Gemini 전처리 | 총 소요 |
|---|---|---|---|
| 5분 | ~5초 | ~1분 | ~1.5분 |
| 30분 | ~30초 | ~6분 | ~8분 |
| 1시간 | ~1분 | ~12분 | ~18분 |

> Whisper API 기준 (24MB 이하), 화자 구분 포함 시 +3~5분

---

## 개발 로드맵

- [x] v0.1.0: CLI 파이프라인
- [x] v0.2.0: Electron 데스크탑 앱
- [x] v0.3.0: Whisper API + Gemini 병렬처리 + 한국어 최적화
- [x] v0.4.0: 단계별 파이프라인 + 화자 라벨링 UI + 프로젝트 파일
- [ ] v0.5.0: UI 최적화
  - [ ] 중앙 뷰에 선택된 프로젝트 요약 표시
  - [ ] 완료된 파일 목록 + 파일 열기 버튼
  - [ ] 폰트, 간격, 색상 정리
- [ ] v1.0.0: .exe 패키징