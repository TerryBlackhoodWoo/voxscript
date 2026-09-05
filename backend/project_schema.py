"""
VOXScript - Project File Schema (.vox)
프로젝트 상태를 JSON으로 저장/로드
"""

import os
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from enum import Enum


class PipelineStage(str, Enum):
    INIT = "init"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    CLEANING = "cleaning"
    LABELING = "labeling"
    DIARIZING = "diarizing"
    TRANSLATING = "translating"
    SAVING = "saving"
    DONE = "done"
    ERROR = "error"


@dataclass
class SegmentData:
    index: int
    start: float
    end: float
    text: str
    translated: Optional[str] = None
    speaker: Optional[str] = None
    speaker_confirmed: bool = False


@dataclass
class ProjectSettings:
    source: str = ""
    lang: str = "auto"
    target_lang: str = "KO"
    format: str = "all"
    model_size: str = "medium"
    use_summary: bool = True
    speakers: list[str] = field(default_factory=list)


@dataclass
class VoxProject:
    version: str = "0.4.0"
    project_id: str = ""
    original_name: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    stage: PipelineStage = PipelineStage.INIT
    stage_progress: int = 0
    error_msg: str = ""
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    segments: list[SegmentData] = field(default_factory=list)
    detected_language: str = ""
    audio_path: str = ""
    summary: str = ""
    project_dir: str = ""
    files: list[str] = field(default_factory=list)


_data_dir_env = os.environ.get("VOXSCRIPT_DATA_DIR")
_BASE_DIR = (
    Path(_data_dir_env) if _data_dir_env else (Path.home() / "Downloads" / "VOXScript")
)

DEFAULT_PROJECTS_DIR = _BASE_DIR / "projects"


def new_project(
    source: str, original_name: str, settings: ProjectSettings
) -> VoxProject:
    import uuid

    now = time.time()
    project_id = str(uuid.uuid4())[:8]
    DEFAULT_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    return VoxProject(
        version="0.4.0",
        project_id=project_id,
        original_name=original_name,
        created_at=now,
        updated_at=now,
        stage=PipelineStage.INIT,
        settings=settings,
        project_dir=str(DEFAULT_PROJECTS_DIR),
    )


def save_project(project: VoxProject) -> Path:
    """프로젝트를 {project_id}.vox 파일로 저장"""
    project.updated_at = time.time()
    project_dir = Path(project.project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    # 파일명에 특수문자 제거
    import re

    safe_name = (
        re.sub(r"[^\w\-]", "_", project.original_name)[:30]
        if project.original_name
        else "project"
    )
    vox_path = project_dir / f"{safe_name}_{project.project_id}.vox"

    data = asdict(project)
    data["stage"] = project.stage.value

    with open(vox_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[Project] Saved: {vox_path}")
    return vox_path


def load_project(vox_path: Path) -> VoxProject:
    with open(vox_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    settings_data = data.pop("settings", {})
    settings = ProjectSettings(**settings_data)
    segments_data = data.pop("segments", [])
    segments = [SegmentData(**s) for s in segments_data]
    data["stage"] = PipelineStage(data.get("stage", "init"))

    project = VoxProject(settings=settings, segments=segments, **data)
    return project


def find_project_file(
    project_id: str, projects_dir: Optional[Path] = None
) -> Path | None:
    """project_id로 저장된 .vox 파일 경로 찾기.

    save_project()는 {project_dir}/{이름}_{project_id}.vox 형태로 평평하게(flat)
    저장하므로, project_id로 찾을 때도 같은 패턴(끝이 _{project_id}.vox)으로 찾아야 함.
    """
    base = projects_dir or DEFAULT_PROJECTS_DIR
    if not base.exists():
        return None
    matches = list(base.glob(f"*_{project_id}.vox"))
    return matches[0] if matches else None


def list_projects(projects_dir: Optional[Path] = None) -> list[dict]:
    base = projects_dir or DEFAULT_PROJECTS_DIR
    if not base.exists():
        return []

    projects = []
    for vox_path in sorted(
        base.glob("*.vox"), key=lambda p: p.stat().st_mtime, reverse=True
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
