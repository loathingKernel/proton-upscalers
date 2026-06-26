import urllib.request
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse

import requests

from upscalers.common import repo_url, log, config, create_redist

_amd_amdxcffx64_version_url = f"{repo_url}/version_amd_amdxcffx64.txt"
_valve_amdxcffx64_version_url = f"{repo_url}/version_valve_amdxcffx64.txt"


__fsr4_dlls: dict[str, dict] = {
    "4.0.0": {
        "version": "4.0.0_67A4D2BC10ad000",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/67A4D2BC10ad000/amdxcffx64.dll",
    },
    "4.0.1": {
        "version": "4.0.1_67D435F7d97000",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/67D435F7d97000/amdxcffx64.dll",
    },
    "4.0.2": {
        "version": "4.0.2_68840348eb8000",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/68840348eb8000/amdxcffx64.dll",
    },
    "4.0.3": {
        "version": "4.0.3_6930960536b9000",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/6930960536b9000/amdxcffx64.dll",
    },
    "4.1.0": {
        "version": "4.1.0_69A0952A304a000",
        "download_url": "https://download.amd.com/dir/bin/amdxcffx64.dll/69A0952A304a000/amdxcffx64.dll",
    },
}


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


def check_amd_amdxcffx64_update() -> tuple[bool, str]:
    pass


def check_valve_amdxcffx64_update() -> tuple[bool, str]:
    pass


def package() -> dict:
    group_entries = []

    amd_version = "4.0.0"
    for version in __fsr4_dlls:
        item = __fsr4_dlls[version]

        if __dll_download_exists(item["download_url"]):
            amd_version = version
            log.crit(f'Downloading version "{version}"')

            item_resp = requests.get(item["download_url"])
            entry = create_redist(
                item_resp.content, "amdxcffx64", version, "FSR4 Driver DLL"
            )
            group_entries.append(entry)

    amd_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_amd_amdxcffx64_version_url).path)).name
    )
    with amd_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(amd_version)

    # set in workflow
    src_path = config.paths.sources.joinpath("proton_experimental")
    with src_path.joinpath("version").open("r") as proton_ver_fd:
        valve_version = proton_ver_fd.read().split(" ")[1]

    version = "4.1.1"
    in_file = src_path.joinpath("contrib", "amdxcffx64.dll")
    with in_file.open("rb") as in_file_fd:
        entry = create_redist(
            in_file_fd.read(), "amdxcffx64", version, "FSR4 Driver DLL"
        )
    group_entries.append(entry)

    valve_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_valve_amdxcffx64_version_url).path)).name
    )
    with valve_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(valve_version)

    return {"fsr_40_drv": group_entries}


if __name__ == "__main__":
    from pprint import pprint

    entries = package()
    pprint(entries)


__all__ = ["package"]
