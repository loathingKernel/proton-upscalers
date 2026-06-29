import urllib.request
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse

import requests

from upscalers.common import repo_url, log, config, create_redist, get_local_version

_amd_version_url = f"{repo_url}/version_amd_amdxcffx64.txt"
_proton_version_url = f"{repo_url}/version_proton_amdxcffx64.txt"


__amd_dlls: list[dict[str, str]] = [
    {
        "version": "4.0.0",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/67A4D2BC10ad000/amdxcffx64.dll",
    },
    {
        "version": "4.0.1",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/67D435F7d97000/amdxcffx64.dll",
    },
    {
        "version": "4.0.2",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/68840348eb8000/amdxcffx64.dll",
    },
    {
        "version": "4.0.3",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/6930960536b9000/amdxcffx64.dll",
    },
    {
        "version": "4.1.0",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/69A0952A304a000/amdxcffx64.dll",
    },
]


@lru_cache(maxsize=32)
def __dll_download_exists(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                log.crit(f"Found reachable URL {url}")
                return True
    except (HTTPError, URLError, ValueError) as e:
        log.crit(f"URL {url} returned {e}")
    return False


def check_amd_update() -> tuple[bool, str]:
    remote_version = __amd_dlls[0]["version"]

    for item in __amd_dlls:
        if __dll_download_exists(item["download_url"]):
            resp = requests.head(item["download_url"])
            remote_version = f'{item["version"]}-{resp.headers["last-modified"]}'

    local_version = get_local_version(_amd_version_url)
    log.crit(f"version amdxcffx64_amd: {local_version=} {remote_version=}")
    if local_version == remote_version:
        return False, remote_version

    return True, remote_version


def check_proton_update() -> tuple[bool, str]:
    remote_version = ""
    src_path = config.paths.sources.joinpath("proton_experimental")
    with src_path.joinpath("version").open("r") as proton_ver_fd:
        remote_version = proton_ver_fd.read().split(" ")[1]

    local_version = get_local_version(_proton_version_url)
    log.crit(f"version amdxcffx64_proton: {local_version=} {remote_version=}")
    if local_version == remote_version:
        return False, remote_version

    return True, remote_version


def package() -> dict:
    group_entries = []

    amd_version = __amd_dlls[0]["version"]
    for item in __amd_dlls:

        if __dll_download_exists(item["download_url"]):
            log.crit(f'Downloading version "{item["version"]}"')

            resp = requests.get(item["download_url"])
            entry = create_redist(
                resp.content, "amdxcffx64", item["version"], "FSR4 Driver DLL"
            )
            amd_version = f'{item["version"]}-{resp.headers["last-modified"]}'
            group_entries.append(entry)

    amd_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_amd_version_url).path)).name
    )
    with amd_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(amd_version)

    # set in workflow
    src_path = config.paths.sources.joinpath("proton_experimental")
    with src_path.joinpath("version").open("r") as proton_ver_fd:
        proton_version = proton_ver_fd.read().split(" ")[1]

    version = "4.1.1"
    in_file = src_path.joinpath("contrib", "amdxcffx64.dll")
    with in_file.open("rb") as in_file_fd:
        entry = create_redist(
            in_file_fd.read(), "amdxcffx64", version, "FSR4 Driver DLL"
        )
    group_entries.append(entry)

    proton_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_proton_version_url).path)).name
    )
    with proton_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(proton_version)

    return {"fsr_40_drv": group_entries}


if __name__ == "__main__":
    from pprint import pprint

    amd_update = check_amd_update()
    pprint(amd_update)

    entries = package()
    pprint(entries)


__all__ = ["check_amd_update", "check_proton_update", "package"]
