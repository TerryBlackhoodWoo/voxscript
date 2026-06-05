"""
VOXScript - Project File Schema (.vox)
프로젝트 상태를 JSON으로 저장/로드
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from enum import Enum


class PipelineStage(str, Enum):
    INIT = "init"  # 초기 상태
    DOWNLOADING = "downloading"  # 1단계: 다운로드 중
    TRANSCRIBING = "transcribing"  # 1단계: Whisper STT 중
    CLEANING = "cleaning"  # 1단계: Gemini 전처리 중
    LABELING = "labeling"  # 2단계: 화자 라벨링 대기 (유저 개입)
    DIARIZING = "diarizing"  # 3단계: 나머지 화자 자동 fill 중
    TRANSLATING = "translating"  # 4단계: DeepL 번역 중
    SAVING = "saving"  # 5단계: 저장 중
    DONE = "done"  # 완료
    ERROR = "error"  # 오류


@dataclass
class SegmentData:
    """단일 세그먼트 데이터"""

    index: int
    start: float
    end: float
    text: str  # Gemini 전처리된 원문
    translated: Optional[str] = None  # DeepL 번역 결과
    speaker: Optional[str] = None  # 화자 라벨 (유저 or Gemini)
    speaker_confirmed: bool = False  # 유저가 직접 확인한 라벨


@dataclass
class ProjectSettings:
    """프로젝트 설정"""

    source: str  # 원본 소스 (URL or 파일경로)
    lang: str = "auto"  # 원본 언어
    target_lang: str = "KO"  # 번역 타겟
    format: str = "all"  # 출력 포맷
    model_size: str = "medium"  # Whisper 모델
    use_summary: bool = True  # Gemini 요약
    speakers: list[str] = field(default_factory=list)  # 화자 이름 목록


@dataclass
class VoxProject:
    """VOXScript 프로젝트 파일"""

    # 메타데이터
    version: str = "0.4.0"
    project_id: str = ""
    original_name: str = ""  # 원본 파일명 (폴더명 기반)
    created_at: float = 0.0
    updated_at: float = 0.0

    # 파이프라인 상태
    stage: PipelineStage = PipelineStage.INIT
    stage_progress: int = 0  # 현재 단계 진행률 (0~100)
    error_msg: str = ""

    # 설정
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    # 데이터
    segments: list[SegmentData] = field(default_factory=list)
    detected_language: str = ""
    audio_path: str = ""  # 임시 mp3 경로
    summary: str = ""  # Gemini 요약

    # 저장 경로
    project_dir: str = ""  # 프로젝트 폴더 경로


# ── 프로젝트 저장/로드 ─────────────────────────────────

DEFAULT_PROJECTS_DIR = Path.home() / "Downloads" / "VOXScript" / "projects"


def new_project(
    source: str, original_name: str, settings: ProjectSettings
) -> VoxProject:
    """새 프로젝트 생성"""
    import uuid

    now = time.time()
    project_id = str(uuid.uuid4())[:8]

    project_dir = DEFAULT_PROJECTS_DIR / original_name
    project_dir.mkdir(parents=True, exist_ok=True)

    return VoxProject(
        version="0.4.0",
        project_id=project_id,
        original_name=original_name,
        created_at=now,
        updated_at=now,
        stage=PipelineStage.INIT,
        settings=settings,
        project_dir=str(project_dir),
    )


def save_project(project: VoxProject) -> Path:
    """프로젝트를 .vox 파일로 저장"""
    project.updated_at = time.time()
    project_dir = Path(project.project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    vox_path = project_dir / "project.vox"

    # dataclass → dict 변환
    data = asdict(project)
    data["stage"] = project.stage.value  # Enum → string

    with open(vox_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[Project] Saved: {vox_path}")
    return vox_path


def load_project(vox_path: Path) -> VoxProject:
    """프로젝트 파일 로드"""
    with open(vox_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # settings 복원
    settings_data = data.pop("settings", {})
    settings = ProjectSettings(**settings_data)

    # segments 복원
    segments_data = data.pop("segments", [])
    segments = [SegmentData(**s) for s in segments_data]

    # stage Enum 복원
    data["stage"] = PipelineStage(data.get("stage", "init"))

    project = VoxProject(settings=settings, segments=segments, **data)
    print(f"[Project] Loaded: {vox_path} (stage: {project.stage.value})")
    return project


def list_projects(projects_dir: Path = None) -> list[dict]:
    """저장된 프로젝트 목록 반환"""
    base = projects_dir or DEFAULT_PROJECTS_DIR
    if not base.exists():
        return []

    projects = []
    for vox_path in sorted(
        base.glob("*/project.vox"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            project = load_project(vox_path)
            projects.append(
                {
                    "project_id": project.project_id,
                    "original_name": project.original_name,
                    "stage": project.stage.value,
                    "created_at": project.created_at,
                    "updated_at": project.updated_at,
                    "vox_path": str(vox_path),
                    "is_done": project.stage == PipelineStage.DONE,
                    "has_error": project.stage == PipelineStage.ERROR,
                }
            )
        except Exception as e:
            print(f"[Project] Failed to load {vox_path}: {e}")

    return projects
