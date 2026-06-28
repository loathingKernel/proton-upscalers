from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from upscalers.common import (
    repo_url,
    log,
    config,
    get_github_releases,
    check_github_update,
    create_redist,
)

_github_api_url = (
    "https://api.github.com/repos/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/releases"
)
_version_url = f"{repo_url}/version_fidelityfx.txt"


def _download_url(tag: str, file: str) -> str:
    return f"https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/refs/tags/{tag}/Kits/FidelityFX/signedbin/{file}"


def get_releases() -> dict:
    return get_github_releases(_github_api_url)


def check_update() -> tuple[bool, str]:
    return check_github_update(_github_api_url, _version_url)


_ffx4_versions = [
    {"tag": "v2.0.0", "version": "4.0.2"},
    {"tag": "v2.1.1", "version": "4.0.3"},
    {"tag": "v2.2.0", "version": "4.1.0"},
]


_ffx4_files = [
    {"group": "fsr_40_fg_dx12", "name": "amd_fidelityfx_framegeneration_dx12.dll"},
    {"group": "fsr_40_ldr_dx12", "name": "amd_fidelityfx_loader_dx12.dll"},
    {"group": "fsr_40_up_dx12", "name": "amd_fidelityfx_upscaler_dx12.dll"},
]


def package() -> dict:
    manifest_entries = {}

    for file in _ffx4_files:
        group_entries = []
        for version in _ffx4_versions:
            url = _download_url(version["tag"], file["name"])

            log.crit(f'Downloading file "{file["name"]}"')
            resp = requests.get(url, timeout=10)
            entry = create_redist(
                resp.content, file["group"], version["version"], "FidelityFX FSR4"
            )
            group_entries.append(entry)

        manifest_entries[file["group"]] = group_entries

    version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_version_url).path)).name
    )
    with version_file.open("w") as out_ver_fd:
        out_ver_fd.write(_ffx4_versions[-1]["tag"])

    return manifest_entries


if __name__ == "__main__":
    from pprint import pprint

    entries = package()
    pprint(entries)

__all__ = ["package"]
