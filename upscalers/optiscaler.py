import hashlib
import io
import subprocess
import tarfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import py7zr
import requests
from configupdater import ConfigUpdater

from upscalers.common import (
    repo_url,
    log,
    config,
    version_tuple,
    get_github_releases,
    check_github_update,
)

_github_api_url = "https://api.github.com/repos/optiscaler/OptiScaler/releases"
_version_url = f"{repo_url}/version_optiscaler.txt"


def get_releases() -> dict:
    return get_github_releases(_github_api_url)


def check_update() -> bool:
    return check_github_update(_github_api_url, _version_url)


_package_files = (
    "OptiScaler.dll",
    "OptiScaler.ini",
    "amd_fidelityfx_dx12.dll",
    "amd_fidelityfx_framegeneration_dx12.dll",
    "amd_fidelityfx_upscaler_dx12.dll",
    "amd_fidelityfx_vk.dll",
    "fakenvapi.dll",
    "fakenvapi.ini",
)


def package() -> dict:
    releases = [
        r
        for r in get_releases()
        if version_tuple(r["tag_name"]) >= version_tuple("v0.9.1")
    ]
    releases = releases[-min(len(releases), 2) :]
    log.crit(f"Found optiscaler versions: {[rel['tag_name'] for rel in releases]}")

    manifest_entries = []
    for rel in reversed(releases):
        log.crit(f"Packaging optiscaler {rel['tag_name']}")
        try:
            resp = requests.get(rel["assets"][0]["browser_download_url"], timeout=10)
        except requests.exceptions.Timeout:
            continue

        src_path = config.paths.sources.joinpath(f"optiscaler_{rel['tag_name']}")
        src_path.mkdir(parents=True, exist_ok=True)
        with io.BytesIO(resp.content) as bytes_fd:
            with py7zr.SevenZipFile(bytes_fd) as archive_fd:
                names = archive_fd.getnames()
                wanted = [n for n in names if n in _package_files]
            archive = src_path.with_name(f"optiscaler_{rel['tag_name']}.7z")
            with archive.open("wb") as file_fd:
                file_fd.write(bytes_fd.getvalue())
        ec = subprocess.call(
            ["7z", "e", "-y", f"-o{str(src_path)}", str(archive), *wanted],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Prepare file structure
        if "amd_fidelityfx_dx12.dll" in wanted:
            src_path.joinpath("amd_fidelityfx_dx12.dll").rename(
                src_path.joinpath("amd_fidelityfx_loader_dx12.dll")
            )
        for link in ("d3d12.dll", "dbghelp.dll", "dxgi.dll"):
            src_path.joinpath(link).unlink(missing_ok=True)
            src_path.joinpath(link).symlink_to("OptiScaler.dll")

        # Update ini
        ini = ConfigUpdater()
        ini.read(src_path.joinpath("OptiScaler.ini"))
        if ini.has_section("Libraries"):
            if ini.has_option("Libraries", "OptiDllPath".lower()):
                ini["Libraries"]["OptiDllPath"].value = "c:\\windows\\system32\\umu"
        else:
            raise RuntimeError(
                "OptiScaler: Could not edit config in version %s", rel["tag_name"]
            )
        ini.update_file(validate=True)

        # Create archive
        md5_hash = {}
        for dll in src_path.glob("*.dll"):
            with dll.open("rb") as dll_fd:
                md5_hash[dll.name] = hashlib.md5(dll_fd.read()).hexdigest().upper()

        tar_path = config.paths.assets.joinpath(f"optiscaler_{rel['tag_name']}.tar.xz")
        tar_path.unlink(missing_ok=True)
        with tarfile.open(tar_path, "x:xz") as tar_fd:
            for path in src_path.iterdir():
                tar_fd.add(path, arcname=path.name)
        with tar_path.open("rb") as tar_fd:
            zip_md5_hash = hashlib.md5(tar_fd.read()).hexdigest().upper()

        entry = {
            "version": rel["tag_name"].lstrip("v"),
            "download_url": f"{repo_url}/{tar_path.name}",
            "file_description": "OptiScaler",
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

    return {"optiscaler": manifest_entries}


if __name__ == "__main__":
    from pprint import pprint

    _update = check_update()
    if _update:
        entries = package()
        pprint(entries)

__all__ = ["check_update", "package"]
