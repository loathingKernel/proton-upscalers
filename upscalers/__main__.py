import hashlib
import json
import lzma
import multiprocessing
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Union
from urllib.parse import unquote, urlparse

from upscalers.common import github_event, repo_url, log, config
import upscalers.optiscaler as optiscaler
import upscalers.fidelityfx as fidelityfx

_manifest_url = "https://raw.githubusercontent.com/beeradmoore/dlss-swapper-manifest-builder/refs/heads/main/manifest.json"
_version_url = f"{repo_url}/version_dlss_swapper.txt"


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


def _download_dlss_swapper_file(url: str, dst: Path, *, checksum: Union[str, None] = None) -> None:
    """Downloads a file and checks against a checksum.

    If the download fails or the checksums do not match, the file is removed and the exception is
    propagated to the caller.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:40.0) Gecko/20100101 Proton/10.0"}, )
    try:
        with dst.open("wb") as dst_fd:
            with urllib.request.urlopen(request, timeout=10) as url_fd:
                dst_fd.write(url_fd.read())
        with dst.open("rb") as dst_fd:
            dst_md5 = hashlib.md5(dst_fd.read()).hexdigest().lower()
        dst_size = dst.stat().st_size if dst.exists() else 0
        # Size check is arbitrary, but nothing should be below 1K
        if (checksum is not None and dst_md5 != checksum.lower()) or dst_size < 1024:
            raise RuntimeError(f"Malformed download {str(dst)}")
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise e


def _package_dlss_swapper(file: dict):
    url_path = Path(unquote(urlparse(file["download_url"]).path))
    in_file = config.paths.sources.joinpath(url_path.name)
    zip_md5 = file.get("zip_md5_hash", None)
    log.crit(f"Downloading file {in_file}")
    _download_dlss_swapper_file(file["download_url"], in_file, checksum=zip_md5)
    out_file = config.paths.assets.joinpath(url_path.name).with_suffix(".xz")
    log.crit(f"Compressing file {out_file}")
    with zipfile.ZipFile(in_file) as zip_fd:
        if len(zip_fd.infolist()) > 1:
            raise RuntimeError(
                f"Archive {in_file.name} contains more than one files: {[info.filename for info in zip_fd.infolist()]}")
        info = zip_fd.infolist()[0]
        with lzma.open(out_file, mode="wb", preset=9) as lzma_fd:
            lzma_fd.write(zip_fd.read(info.filename))
    with out_file.open("rb") as out_fd:
        xz_md5_hash = hashlib.md5(out_fd.read()).hexdigest().upper()
    file["download_url"] = f"{repo_url}/{out_file.name}"
    file["zip_md5_hash"] = xz_md5_hash


def _check_dlss_swapper_update(manifest_md5) -> bool:
    try:
        with urllib.request.urlopen(_version_url, timeout=10) as url_fd:
            version_md5 = url_fd.read().strip().decode("utf-8")
            if version_md5 == manifest_md5:
                log.crit("Local dlss-swapper manifest is up to date.")
                return False
    except urllib.error.HTTPError as e:
        log.crit(str(e))

    return True


def main() -> int:
    if config.paths.sources.exists():
        shutil.rmtree(config.paths.sources)
    if config.paths.assets.exists():
        shutil.rmtree(config.paths.assets)

    manifest, manifest_md5 = _get_manifest()
    manifest.pop("known_dlls")

    if github_event == "schedule":
        update_dlss_swapper = _check_dlss_swapper_update(manifest_md5)
        update_optiscaler = optiscaler.check_update()
        update_fidelityfx = update_dlss_swapper or update_optiscaler
    else:
        update_dlss_swapper = update_optiscaler = update_fidelityfx = True

    if not any((update_dlss_swapper, update_optiscaler, update_fidelityfx)):
        log.crit("Nothing to do")
        return 1

    version_file = config.paths.assets.joinpath(Path(unquote(urlparse(_version_url).path)).name)
    with version_file.open("w") as out_ver_fd:
        out_ver_fd.write(manifest_md5)

    upscalers = (key for key in manifest.keys() if key not in {"known_dlls", })
    for upscaler in upscalers:
        dlls = manifest[upscaler]
        log.crit(f"Found {len(dlls)} files for {upscaler}")
        dlls = tuple(dll for dll in dlls if not dll["is_dev_file"])
        log.crit(f"Found {len(dlls)} non-dev files for {upscaler}")
        dlls = dlls[-5:]
        if github_event == "test":
            dlls = dlls[-1:]
        pool = ThreadPoolExecutor(multiprocessing.cpu_count())
        with pool as executor:
            executor.map(_package_dlss_swapper, dlls)

    optiscaler_entries = optiscaler.package()
    manifest.update(optiscaler_entries)

    fidelityfx_entries = fidelityfx.package()
    manifest.update(fidelityfx_entries)

    with config.paths.assets.joinpath("manifest.json").open("w") as out_man_fd:
        out_man_fd.write(json.dumps(manifest))

    return 0


if __name__ == "__main__":
    ec = main()
    sys.exit(ec)
