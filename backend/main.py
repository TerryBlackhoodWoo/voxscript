"""
VOXScript - FastAPI 서버 v0.4.0
단계별 파이프라인 + 프로젝트 파일 기반
"""

import os
import sys
import threading
import asyncio
from DAO import usage_vox_dao
from contextlib import asynccontextmanager

from pathlib import Path
from typing import Optional
import database_pg

# Windows 콘솔 기본 코드페이지(cp949 등)는 ⏸ 같은 이모지/특수문자를 인코딩 못 해서
# print()가 그대로 죽어버림 → stdout/stderr를 UTF-8로 강제 (errors="replace"로 한 번 더 방어)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

from project_schema import (
    VoxProject,
    PipelineStage,
    ProjectSettings,
    SegmentData,
    new_project,
    save_project,
    load_project,
    list_projects,
    find_project_file,
    DEFAULT_PROJECTS_DIR,
)
from DAO.downloader import download_audio
from DAO.transcriber import transcribe, SUPPORTED_LANGUAGES
from DAO.cleaner import clean
from DAO.translator import translate, TARGET_LANGUAGES
from DAO.formatter import format_and_save, OUTPUT_FORMATS
from services import auth_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    await database_pg.connect()
    yield
    await database_pg.close()


app = FastAPI(title="VOXScript API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 메모리 내 프로젝트 캐시 (project_id → VoxProject)
projects: dict[str, VoxProject] = {}
# 로그 캐시
logs: dict[str, list[str]] = {}
# 백그라운드 스레드에서 asyncpg 풀(메인 이벤트 루프 소속)을 안전하게 쓰기 위해 저장
main_event_loop: asyncio.AbstractEventLoop | None = None


# ── 요청 모델 ───────────────────────────────────────────


class StartRequest(BaseModel):
    source: str
    lang: str = "auto"
    target_lang: str = "KO"
    format: str = "all"
    model_size: str = "medium"
    use_summary: bool = True


class ResumeRequest(BaseModel):
    labeled_segments: list[dict]  # [{index, speaker}]
    speakers: list[str] = []  # 유저가 라벨링 화면에서 지정한 화자 이름들


class SaveRequest(BaseModel):
    export_dir: Optional[str] = None  # None = 기본 경로
    formats: Optional[list[str]] = None  # None = 프로젝트 설정 따름


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── 응답 모델 ───────────────────────────────────────────


class ProjectStatus(BaseModel):
    project_id: str
    original_name: str
    stage: str
    stage_progress: int
    segments: list[dict] = []
    detected_language: str = ""
    summary: str = ""
    error_msg: str = ""
    log: list[str] = []
    is_done: bool = False


# ── 헬퍼 ───────────────────────────────────────────────


def _log(project_id: str, msg: str):
    print(f"[VOXScript] {msg}", flush=True)
    if project_id not in logs:
        logs[project_id] = []
    logs[project_id].append(msg)
    if len(logs[project_id]) > 100:
        logs[project_id] = logs[project_id][-100:]


def _update_stage(project: VoxProject, stage: PipelineStage, progress: int = 0):
    project.stage = stage
    project.stage_progress = progress
    save_project(project)


def _project_to_status(project: VoxProject) -> ProjectStatus:
    segs = [
        {
            "index": seg.index,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "translated": seg.translated,
            "speaker": seg.speaker,
            "speaker_confirmed": seg.speaker_confirmed,
        }
        for seg in project.segments
    ]
    return ProjectStatus(
        project_id=project.project_id,
        original_name=project.original_name,
        stage=project.stage.value,
        stage_progress=project.stage_progress,
        segments=segs,
        detected_language=project.detected_language,
        summary=project.summary,
        error_msg=project.error_msg,
        log=logs.get(project.project_id, []),
        is_done=project.stage == PipelineStage.DONE,
    )


# ── 엔드포인트 ─────────────────────────────────────────


@app.get("/")
def root():
    return {"status": "ok", "service": "VOXScript API", "version": "0.4.0"}


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    token = await auth_service.login(req.username, req.password)
    return LoginResponse(access_token=token)


@app.get("/languages")
def get_languages():
    return {"source": SUPPORTED_LANGUAGES, "target": TARGET_LANGUAGES}


@app.get("/formats")
def get_formats():
    return OUTPUT_FORMATS


@app.get("/projects")
def get_projects():
    """저장된 프로젝트 목록 (사이드바용)"""
    return list_projects(DEFAULT_PROJECTS_DIR)


@app.post("/start", response_model=ProjectStatus)
async def start_pipeline(
    req: StartRequest, account: dict = Depends(auth_service.get_current_account)
):
    """1~3단계 실행: 다운로드 → STT → Gemini 전처리 → labeling 대기"""
    used_seconds = await usage_vox_dao.get_current_month_stt_seconds(account["id"])
    limit_seconds = account["monthly_minutes_limit"] * 60
    if used_seconds >= limit_seconds:
        raise HTTPException(
            status_code=429,
            detail=f"이번 달 사용 한도({account['monthly_minutes_limit']}분)를 초과했습니다.",
        )

    settings = ProjectSettings(
        source=req.source,
        lang=req.lang,
        target_lang=req.target_lang,
        format=req.format,
        model_size=req.model_size,
        use_summary=req.use_summary,
    )
    project = new_project(req.source, f"project_{len(projects)+1:03d}", settings)
    projects[project.project_id] = project
    logs[project.project_id] = []

    thread = threading.Thread(
        target=_run_stage1,
        args=(project.project_id, account["id"]),
        daemon=True,
    )
    thread.start()

    return _project_to_status(project)


def _load_from_disk_orphan_safe(project_id: str) -> Optional[VoxProject]:
    """디스크에서 .vox를 불러올 때, "처리 중" 단계인데 이 서버 세션엔 그 처리를
    이어갈 백그라운드 스레드가 없는 좀비 상태면 ERROR로 전환해서 반환.
    (라벨링/저장 대기는 유저 입력을 기다리는 진짜 일시정지라 예외로 둠)
    """
    vox_path = find_project_file(project_id)
    if not vox_path:
        return None

    project = load_project(vox_path)

    ORPHANABLE_STAGES = {
        PipelineStage.INIT,
        PipelineStage.DOWNLOADING,
        PipelineStage.TRANSCRIBING,
        PipelineStage.CLEANING,
        PipelineStage.DIARIZING,
        PipelineStage.TRANSLATING,
    }
    if project.stage in ORPHANABLE_STAGES:
        project.stage = PipelineStage.ERROR
        project.error_msg = (
            "이전 처리가 중단된 상태로 남아있습니다 "
            "(앱이 비정상 종료됐거나 서버가 재시작됨). 처음부터 다시 시작해주세요."
        )
        save_project(project)

    return project


@app.get("/status/{project_id}", response_model=ProjectStatus)
def get_status(project_id: str):
    if project_id not in projects:
        # 파일에서 로드 시도 (flat 저장 구조: *_{project_id}.vox)
        project = _load_from_disk_orphan_safe(project_id)
        if project:
            projects[project_id] = project
        else:
            raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_status(projects[project_id])


@app.post("/resume/{project_id}", response_model=ProjectStatus)
def resume_pipeline(
    project_id: str,
    req: ResumeRequest,
    account: dict = Depends(auth_service.get_current_account),
):
    """2단계 완료: 라벨링 데이터 받아서 3~5단계 실행"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects[project_id]
    if project.stage != PipelineStage.LABELING:
        raise HTTPException(
            status_code=400,
            detail=f"Project is not in labeling stage (current: {project.stage.value})",
        )

    # 유저 라벨링 반영
    label_map = {item["index"]: item["speaker"] for item in req.labeled_segments}
    for seg in project.segments:
        if seg.index in label_map:
            seg.speaker = label_map[seg.index]
            seg.speaker_confirmed = True

    # 유저가 지정한 화자 이름 저장 (나머지 자동 fill에 사용)
    if req.speakers:
        project.settings.speakers = req.speakers
        print(f"[Project] User speakers: {req.speakers}")

    save_project(project)

    thread = threading.Thread(
        target=_run_stage2,
        args=(project_id,),
        daemon=True,
    )
    thread.start()

    return _project_to_status(project)


@app.post("/save/{project_id}", response_model=ProjectStatus)
def save_output(
    project_id: str,
    req: SaveRequest,
    account: dict = Depends(auth_service.get_current_account),
):
    """5단계: 파일 저장"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects[project_id]
    if project.stage != PipelineStage.SAVING:
        raise HTTPException(
            status_code=400,
            detail=f"Project is not ready to save (current stage: {project.stage.value})",
        )

    thread = threading.Thread(
        target=_run_stage3,
        args=(project_id, req.export_dir, req.formats),
        daemon=True,
    )
    thread.start()

    return _project_to_status(project)


@app.get("/me")
async def get_me(account: dict = Depends(auth_service.get_current_account)):
    return {
        "id": str(account["id"]),
        "username": account["username"],
        "is_admin": account["is_admin"],
    }


@app.get("/load/{project_id}", response_model=ProjectStatus)
def load_saved_project(project_id: str):
    """저장된 프로젝트 이어하기 (flat 저장 구조: *_{project_id}.vox)"""
    # 이미 이 서버 세션에서 추적 중인 프로젝트면(=처리 스레드가 실제로 살아있을 수
    # 있음) 디스크에서 다시 읽지 않고 그대로 반환
    if project_id in projects:
        return _project_to_status(projects[project_id])

    project = _load_from_disk_orphan_safe(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    projects[project_id] = project
    return _project_to_status(project)


# ── 파이프라인 스테이지 ────────────────────────────────


def _run_stage1(project_id: str, account_id: str):
    """1단계: 다운로드 → STT → Gemini 전처리 → labeling 대기"""
    import time as _time

    project = projects[project_id]

    try:

        def progress(step, pct):
            project.stage_progress = pct

        # Step 1: 다운로드
        _update_stage(project, PipelineStage.DOWNLOADING, 5)
        _log(project_id, f"[1/3] Downloading: {project.settings.source[:60]}...")
        t = _time.time()

        audio_path, original_name = download_audio(
            project.settings.source,
            f"project_{project_id}",
        )
        if original_name:
            project.original_name = original_name
            from project_schema import DEFAULT_PROJECTS_DIR

            DEFAULT_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            project.project_dir = str(DEFAULT_PROJECTS_DIR)

        project.audio_path = str(audio_path)
        _log(
            project_id,
            f"[1/3] Download complete [{_time.time()-t:.1f}s] → {audio_path.name}",
        )

        # Step 2: STT
        _update_stage(project, PipelineStage.TRANSCRIBING, 25)
        _log(project_id, f"[2/3] Whisper STT starting (lang: {project.settings.lang})")
        t = _time.time()

        transcribe_result = transcribe(
            str(audio_path),
            language=project.settings.lang,
            model_size=project.settings.model_size,
            progress_callback=progress,
        )
        project.detected_language = transcribe_result.detected_language
        _log(
            project_id,
            f"[2/3] STT complete [{_time.time()-t:.1f}s] → {len(transcribe_result.segments)} segments, lang={transcribe_result.detected_language}",
        )

        # 사용량 기록 (마지막 세그먼트 종료 시각 ≈ 오디오 길이)
        duration_seconds = int(
            max((seg.end for seg in transcribe_result.segments), default=0)
        )
        if main_event_loop is None:
            raise RuntimeError(
                "메인 이벤트 루프가 아직 초기화되지 않았습니다 (서버 시작 순서 문제)."
            )

        future = asyncio.run_coroutine_threadsafe(
            usage_vox_dao.add_stt_seconds(account_id, duration_seconds), main_event_loop
        )
        future.result()
        _log(project_id, f"[사용량] {duration_seconds}초 기록됨")

        # Step 3: Gemini 전처리
        _update_stage(project, PipelineStage.CLEANING, 61)
        _log(
            project_id,
            f"[3/3] Gemini preprocessing ({len(transcribe_result.segments)} segments)...",
        )
        t = _time.time()

        cleaned_result = clean(transcribe_result, progress_callback=progress)
        _log(
            project_id,
            f"[3/3] Preprocessing complete [{_time.time()-t:.1f}s] → {cleaned_result.cleaned_count} segments",
        )

        project.segments = [
            SegmentData(
                index=seg.index,
                start=seg.start,
                end=seg.end,
                text=seg.text,
            )
            for seg in cleaned_result.segments
        ]

        _update_stage(project, PipelineStage.LABELING, 0)
        _log(project_id, "⏸ Waiting for speaker labeling...")

    except Exception as e:
        project.stage = PipelineStage.ERROR
        project.error_msg = str(e)
        save_project(project)
        _log(project_id, f"❌ Error: {e}")


def _run_stage2(project_id: str):
    """3~4단계: 화자 자동 fill → 번역"""
    import time as _time

    project = projects[project_id]

    try:

        def progress(step, pct):
            project.stage_progress = pct

        # Step 3: 화자 자동 fill (Gemini)
        confirmed = [s for s in project.segments if s.speaker_confirmed]
        _log(
            project_id,
            f"[3] Speaker diarization ({len(confirmed)} confirmed labels)...",
        )
        _update_stage(project, PipelineStage.DIARIZING, 0)
        t = _time.time()

        if len(confirmed) > 0 or project.settings.speakers:
            from DAO.diarizer import label_speakers
            from DAO.translator import TranslatedSegment, TranslationResult

            # 임시 TranslatedSegment 구조로 변환 (diarizer 입력용)
            class TempSeg:
                def __init__(self, seg):
                    self.index = seg.index
                    self.translated = seg.text

            temp_segs = [TempSeg(s) for s in project.segments]
            speaker_map = label_speakers(
                temp_segs,
                speakers=project.settings.speakers,  # 항상 list (빈 리스트도 diarizer의 truthy 체크와 동일하게 동작)
                progress_callback=progress,
            )

            # 유저 확인 라벨 우선, 나머지는 Gemini 결과
            for seg in project.segments:
                if not seg.speaker_confirmed:
                    label = speaker_map.get(seg.index, "")
                    if label:
                        seg.speaker = label

        _log(project_id, f"[3] Diarization complete [{_time.time()-t:.1f}s]")

        # Step 4: 번역
        _update_stage(project, PipelineStage.TRANSLATING, 0)
        src_lang = project.detected_language

        if project.settings.target_lang == "KO" and src_lang.lower() in (
            "ko",
            "korean",
        ):
            _log(project_id, "[4] Korean source, skipping translation")
            for seg in project.segments:
                seg.translated = seg.text
        else:
            _log(
                project_id,
                f"[4] DeepL translating ({len(project.segments)} segments)...",
            )
            t = _time.time()

            from DAO.cleaner import CleanedResult, CleanedSegment

            cleaned_segments = [
                CleanedSegment(s.index, s.start, s.end, s.text)
                for s in project.segments
            ]
            cleaned_result = CleanedResult(
                segments=cleaned_segments,
                detected_language=src_lang,
                original_count=len(project.segments),
                cleaned_count=len(project.segments),
            )
            translation_result = translate(
                cleaned_result,
                target_lang=project.settings.target_lang,
                progress_callback=progress,
            )

            # 번역 결과 반영
            trans_map = {
                seg.index: seg.translated for seg in translation_result.segments
            }
            for seg in project.segments:
                seg.translated = trans_map.get(seg.index, seg.text)

            _log(project_id, f"[4] Translation complete [{_time.time()-t:.1f}s]")

        # 저장 대기 상태로
        _update_stage(project, PipelineStage.SAVING, 0)
        _log(project_id, "⏸ Ready to save. Choose export path.")

    except Exception as e:
        project.stage = PipelineStage.ERROR
        project.error_msg = str(e)
        save_project(project)
        _log(project_id, f"❌ Error: {e}")


def _run_stage3(
    project_id: str, export_dir: Optional[str] = None, formats: Optional[list] = None
):
    """5단계: 파일 저장"""
    import time as _time

    project = projects[project_id]

    try:
        _log(project_id, "[5] Saving files...")
        t = _time.time()

        # TranslationResult 임시 구조 생성
        from DAO.translator import TranslationResult, TranslatedSegment

        trans_segs = []
        for seg in project.segments:
            # 화자 라벨 붙이기
            orig = f"[{seg.speaker}] {seg.text}" if seg.speaker else seg.text
            tran = (
                f"[{seg.speaker}] {seg.translated}"
                if seg.speaker and seg.translated
                else (seg.translated or seg.text)
            )

            trans_segs.append(
                TranslatedSegment(
                    index=seg.index,
                    start=seg.start,
                    end=seg.end,
                    original=orig,
                    translated=tran,
                )
            )

        translation_result = TranslationResult(
            segments=trans_segs,
            source_language=project.detected_language,
            target_language=project.settings.target_lang,
        )

        fmt_list = formats or [project.settings.format]
        export_path = Path(export_dir) if export_dir else None

        format_result = format_and_save(
            translation_result,
            output_name=project.original_name,
            formats=fmt_list,
            export_dir=export_path,
            use_claude_summary=project.settings.use_summary,
        )

        project.summary = format_result.claude_summary or ""
        _update_stage(project, PipelineStage.DONE, 100)  # save_project 내부 호출
        _log(
            project_id,
            f"[5] Saved {len(format_result.saved_files)} files [{_time.time()-t:.1f}s]",
        )
        _log(project_id, f"✅ Done!")

    except Exception as e:
        project.stage = PipelineStage.ERROR
        project.error_msg = str(e)
        save_project(project)
        _log(project_id, f"❌ Error: {e}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("VOXSCRIPT_PORT", 8765))
    print(f"[VOXScript] API server starting: http://localhost:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
