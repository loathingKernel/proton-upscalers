import hashlib
import io
import os
import re
import tarfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from upscalers.common import (
    check_github_update,
    config,
    get_github_releases,
    log,
    repo_url,
)

_github_api_url = "https://api.github.com/repos/NVIDIA-RTX/Streamline/releases"
_version_url = f"{repo_url}/version_streamline.txt"


def get_releases() -> dict:
    return get_github_releases(_github_api_url)


def check_update() -> tuple[bool, str]:
    return check_github_update("streamline", _github_api_url, _version_url)


_excluded_files = (
    "nvngx_deepdvc.dll",
    "nvngx_dlss.dll",
    "nvngx_dlssd.dll",
)


def package() -> dict:
    releases = get_releases()
    log.crit(f"Found streamline versions: {[rel['tag_name'] for rel in releases]}")

    manifest_entries = []
    url_pattern = re.compile(r"streamline-sdk-v[0-9.]+\.zip")
    for rel in reversed(releases):
        log.crit(f"Packaging streamline {rel['tag_name']}")
        # streamline-sdk-v[0-9.]+(?!-aarch64|-arm64ec)\.zip
        # streamline-sdk-v[0-9.]+\.zip
        asset_urls = [a["browser_download_url"] for a in rel["assets"]]
        for url in asset_urls:
            if re.search(url_pattern, url):
                break
        else:
            log.crit(f"Did not find matching download url in {asset_urls}")
            continue

        try:
            resp = requests.get(url, timeout=10)
        except requests.exceptions.Timeout:
            continue

        src_path = config.paths.sources.joinpath(f"streamline_{rel['tag_name']}")
        src_path.mkdir(parents=True, exist_ok=True)
        with (
            io.BytesIO(resp.content) as bytes_fd,
            zipfile.ZipFile(bytes_fd) as archive_fd,
        ):
            infolist = archive_fd.infolist()
            wanted = [
                info
                for info in infolist
                if info.filename.startswith("bin/x64")
                and not (
                    info.filename.endswith(_excluded_files)
                    or "development" in info.filename
                    or info.is_dir()
                )
            ]
            log.crit(f"Found wanted files: {[w.filename for w in wanted]}")
            for info in wanted:
                basename = os.path.basename(info.filename)
                with src_path.joinpath(basename).open("wb") as file_fd:
                    file_fd.write(archive_fd.read(info))

        # Create archive
        md5_hash = {}
        for root, dirs, files in src_path.walk():
            for file in files:
                if not file.endswith((".dll",)):
                    continue
                dll = Path(root).joinpath(file)
                with dll.open("rb") as dll_fd:
                    dll_name = dll.relative_to(src_path).as_posix()
                    md5_hash[dll_name] = hashlib.md5(dll_fd.read()).hexdigest().upper()

        tar_path = config.paths.assets.joinpath(f"streamline_{rel['tag_name']}.tar.xz")
        tar_path.unlink(missing_ok=True)
        with tarfile.open(tar_path, "x:xz") as tar_fd:
            for path in src_path.iterdir():
                tar_fd.add(path, arcname=path.name)
        with tar_path.open("rb") as tar_fd:
            zip_md5_hash = hashlib.md5(tar_fd.read()).hexdigest().upper()

        entry = {
            "version": rel["tag_name"].lstrip("v"),
            "download_url": f"{repo_url}/{tar_path.name}",
            "file_description": "streamline",
            "zip_file_size": tar_path.stat().st_size,
            "is_dev_file": False,
            "is_bundle": True,
            "md5_hash": md5_hash,
            "zip_md5_hash": zip_md5_hash,
        }
        manifest_entries.append(entry)

    version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_version_url).path)).name
    )
    with version_file.open("w") as out_ver_fd:
        out_ver_fd.write(releases[0]["tag_name"])

    return {"streamline": manifest_entries}


if __name__ == "__main__":
    from pprint import pprint

    _update, _ = check_update()
    if _update:
        entries = package()
        pprint(entries)

__all__ = ["check_update", "package"]
