# voxscript-backend.spec
#
# 사용법 (backend/ 디렉토리에서 실행):
#   pyinstaller voxscript-backend.spec --distpath ../backend-dist --workpath ../backend-build --noconfirm
#
# package.json의 "build:backend" 스크립트가 이걸 자동으로 호출함.
#
# 로컬 Whisper(CUDA) 폴백은 의도적으로 제외함 (배포판은 API 전용).
# requirements.txt의 openai-whisper(=whisper)와 그 의존성 torch는 excludes로 막아둠.
# main.py / DAO 모듈 실제 코드 기준으로 hidden imports 구성함:
#   - google.genai: cleaner.py / diarizer.py / formatter.py에서 사용
#   - googleapiclient 등: downloader.py의 Google Drive OAuth 흐름에서 사용
#   - uvicorn: main.py가 uvicorn.run()으로 직접 구동
# 그래도 처음 빌드해서 voxscript-backend.exe 실행했을 때 ModuleNotFoundError가
# 뜨면 그 모듈명을 hiddenimports 리스트에 추가하면 됨.

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("googleapiclient")
    + collect_submodules("google.genai")
    + [
        "google_auth_httplib2",
        "google.oauth2.credentials",
        "google_auth_oauthlib.flow",
        "openai",
        "deepl",
        "openpyxl",
        "openpyxl.styles",
        "dotenv",
        "project_schema",
        "DAO",
        "DAO.bin_paths",
        "DAO.downloader",
        "DAO.transcriber",
        "DAO.cleaner",
        "DAO.translator",
        "DAO.diarizer",
        "DAO.formatter",
    ]
)

# google.genai가 런타임에 참조하는 데이터 파일(있다면)도 같이 챙김.
# 없으면 빈 리스트만 반환되니 안전함.
datas = collect_data_files("google.genai")

excluded_modules = [
    "whisper",
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "tkinter",
    "matplotlib",
    # openai-whisper(로컬 CUDA 폴백, 배포판에서 미사용)가 끌고 오는
    # 오디오 처리용 의존성들 — main.py/DAO 어디서도 직접 안 씀
    "numba",
    "llvmlite",
    "scipy",
    "pandas",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    excludes=excluded_modules,
    noarchive=False,
)

# googleapiclient는 기본적으로 Gmail/Sheets/Calendar 등 모든 Google API의
# discovery JSON 문서를 통째로 끌고 와서 ~97MB를 차지함.
# 이 프로젝트는 Drive v3 API만 쓰므로 그것만 남기고 나머지는 제거.
def _is_unneeded_discovery_doc(dest_name: str) -> bool:
    normalized = dest_name.replace("\\", "/")
    if "discovery_cache/documents" not in normalized:
        return False
    return not normalized.endswith("drive.v3.json")


a.datas = [d for d in a.datas if not _is_unneeded_discovery_doc(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voxscript-backend",
    console=False,  # 실기기 테스트(다운로드/STT/deno/.vox 이어하기) 전부 통과 후 적용
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="voxscript-backend",
)
