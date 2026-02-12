import hashlib
import json
import lzma
import multiprocessing
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures.thread import ThreadPoolExecutor
from functools import wraps
from pathlib import Path
from typing import Union
from urllib.parse import unquote, urlparse

_manifest_url = "https://raw.githubusercontent.com/beeradmoore/dlss-swapper-manifest-builder/refs/heads/main/manifest.json"

local_github_user = os.environ.get("UPSCALERS_USER")
local_github_repo = os.environ.get("UPSCALERS_REPO").split("/")[1]
local_github_event = os.environ.get("UPSCALERS_EVENT")
local_repo_url = f"https://{local_github_user}.github.io/{local_github_repo}"
local_manifest_url = f"{local_repo_url}/manifest.json"
local_version_url = f"{local_repo_url}/version.txt"

_entry_cwd = os.getcwd()


def ensure_directory_exists(func):
    @wraps(func)
    def create_directory(cls):
        path = func(cls)
        path.mkdir(parents=True, exist_ok=True)
        return path

    return create_directory


class Log:
    @staticmethod
    def crit(msg: str):
        print(msg, file=sys.stderr)


class Config:
    class Paths:
        @property
        @ensure_directory_exists
        def cache_dir(self) -> Path:
            return Path(_entry_cwd)

        @property
        @ensure_directory_exists
        def sources(self) -> Path:
            return self.cache_dir.joinpath("sources")

        @property
        @ensure_directory_exists
        def assets(self) -> Path:
            return self.cache_dir.joinpath("assets")

    paths = Paths()


log = Log()
config = Config()


def _get_manifest() -> tuple[dict, str]:
    cached_manifest = config.paths.sources.joinpath("manifest.json")
    _manifest_json = {}

    try:
        with urllib.request.urlopen(_manifest_url, timeout=10) as url_fd:
            _manifest_json = json.loads(url_fd.read())
    except Exception as e:
        log.crit(f'Failed to download "{_manifest_url}"')
        log.crit(repr(e))
    else:
        with cached_manifest.open("w", encoding="utf-8") as manifest_fd:
            manifest_fd.write(json.dumps(_manifest_json))

    with cached_manifest.open("rb") as manifest_fd:
        _manifest_md5 = hashlib.md5(manifest_fd.read()).hexdigest().lower()
    return _manifest_json, _manifest_md5  # pyright: ignore [reportReturnType]


def _download_file(url: str, dst: Path, *, checksum: Union[str, None] = None) -> None:
    """Downloads a file and checks against a checksum.

    If the download fails or the checksums do not match, the file is removed and the exception is
    propagated to the caller.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0"
        },
    )
    try:
        with dst.open("wb") as dst_fd:
            with urllib.request.urlopen(request, timeout=10) as url_fd:
                dst_fd.write(url_fd.read())
        dst_md5 = hashlib.md5(dst.open("rb").read()).hexdigest().lower()
        dst_size = dst.stat().st_size if dst.exists() else 0
        # Size check is arbitrary, but nothing should be below 1K
        if (checksum is not None and dst_md5 != checksum.lower()) or dst_size < 1024:
            raise RuntimeError(f"Malformed download {str(dst)}")
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise e


def download_recompress(file: dict):
    url_path = Path(unquote(urlparse(file["download_url"]).path))
    input_file = config.paths.sources.joinpath(url_path.name)
    file_md5 = file.get("zip_md5_hash", None)
    log.crit(f"Downloading file {input_file}")
    _download_file(file["download_url"], input_file, checksum=file_md5)
    output_file = config.paths.assets.joinpath(url_path.name).with_suffix(".xz")
    log.crit(f"Compressing file {output_file}")
    with zipfile.ZipFile(input_file) as zip_fd:
        if len(zip_fd.infolist()) > 1:
            raise RuntimeError(
                f"Archive {input_file.name} contains more than one files: {(info.filename for info in zip_fd.infolist())}"
            )
        info = zip_fd.infolist()[0]
        with lzma.open(output_file, mode="wb", preset=9) as lzma_fd:
            lzma_fd.write(zip_fd.read(info.filename))
    xz_md5_hash = hashlib.md5(output_file.open("rb").read()).hexdigest().upper()
    file["download_url"] = f"{local_repo_url}/{output_file.name}"
    file["zip_md5_hash"] = xz_md5_hash


def main() -> int:
    if config.paths.sources.exists():
        shutil.rmtree(config.paths.sources)
    if config.paths.assets.exists():
        shutil.rmtree(config.paths.assets)

    manifest, manifest_md5 = _get_manifest()

    if local_github_event == "schedule":
        try:
            with urllib.request.urlopen(local_version_url, timeout=10) as url_fd:
                version_md5 = url_fd.read().strip().decode("utf-8")
                if version_md5 == manifest_md5:
                    log.crit("Local manifest is up to date. Aborting")
                    return 1
        except urllib.error.HTTPError as e:
            log.crit(str(e))

    with config.paths.assets.joinpath("version.txt").open("w") as out_ver_fd:
        out_ver_fd.write(manifest_md5)

    upscalers = ( key for key in manifest.keys() if key not in { "known_dlls", } )
    for upscaler in upscalers:
        dlls = manifest[upscaler]
        log.crit(f"Found {len(dlls)} files for {upscaler}")
        dlls = tuple(dll for dll in dlls if not dll["is_dev_file"])
        log.crit(f"Found {len(dlls)} non-dev files for {upscaler}")
        dlls = dlls[-7:]
        pool = ThreadPoolExecutor(multiprocessing.cpu_count())
        with pool as executor:
            executor.map(download_recompress, dlls)

    with config.paths.assets.joinpath("manifest.json").open("w") as out_man_fd:
        out_man_fd.write(json.dumps(manifest))

    return 0


if __name__ == "__main__":
    ec = main()
    sys.exit(ec)
