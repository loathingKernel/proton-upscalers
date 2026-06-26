import hashlib
import io
import os
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

_scaler_github_api_url = "https://api.github.com/repos/optiscaler/OptiScaler/releases"
_scaler_version_url = f"{repo_url}/version_optiscaler.txt"

_patcher_github_api_url = "https://api.github.com/repos/optiscaler/OptiPatcher/releases"
_patcher_version_url = f"{repo_url}/version_optipatcher.txt"


def get_optiscaler_releases() -> dict:
    return get_github_releases(_scaler_github_api_url)


def get_optipatcher_releases() -> dict:
    return get_github_releases(_patcher_github_api_url)


def check_optiscaler_update() -> tuple[bool, str]:
    return check_github_update(_scaler_github_api_url, _scaler_version_url)


def check_optipatcher_update() -> tuple[bool, str]:
    return check_github_update(
        _patcher_github_api_url, _patcher_version_url, comparator="date"
    )


_package_files = (
    "OptiScaler.dll",
    "OptiScaler.ini",
    # "amd_fidelityfx_dx12.dll",
    # "amd_fidelityfx_framegeneration_dx12.dll",
    # "amd_fidelityfx_upscaler_dx12.dll",
    # "amd_fidelityfx_vk.dll",
    "dlssg_to_fsr3_amd_is_better.dll",
    "fakenvapi.dll",
    "fakenvapi.ini",
)


_excluded_processes = (
    "crashpad_handler.exe",
    "crashreport.exe",
    "crashreporter.exe",
    "crs-handler.exe",
    "unitycrashhandler64.exe",
    "idtechlauncher.exe",
    "cefviewwing.exe",
    "ace-setup64.exe",
    "ace-service64.exe",
    "qtwebengineprocess.exe",
    "platformprocess.exe",
    "bugsplathd64.exe",
    "bssndrpt64.exe",
    "pspcsdkappmgr.exe",
    "pspcsdkcore.exe",
    "pspcsdkstttts.exe",
    "pspcsdktelemetry.exe",
    "pspcsdkui.exe",
    "pspcsdkupdatechecker.exe",
    "pspcsdkvoicechat.exe",
    "pspcsdkwebview.exe",
    "windhawk.exe",
    "vscodium.exe",
    "crash_reporter.exe",
    "steamerrorreporter64.exe",
    "crashreportclient.exe",
    "edcefcrashpadprocess.exe",
    "edcefrenderprocess.exe",
    "EOSOverlayRenderer-Win64-Shipping.exe",
    "EOSOverlayRenderer-Win32-Shipping.exe",
)


def package() -> dict:
    scaler_releases = [
        r
        for r in get_optiscaler_releases()
        if version_tuple(r["tag_name"]) >= version_tuple("v0.9.1")
    ]
    scaler_releases = scaler_releases[-min(len(scaler_releases), 7) :]
    log.crit(
        f"Found optiscaler versions: {[rel['tag_name'] for rel in scaler_releases]}"
    )

    patcher_release = get_optipatcher_releases()[0]
    log.crit(f"Found optipatcher version: {patcher_release['updated_at']}")

    try:
        patcher_resp = requests.get(
            patcher_release["assets"][0]["browser_download_url"], timeout=10
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Failed to get OptiPatcher asset.")

    with io.BytesIO(patcher_resp.content) as bytes_fd:
        patcher_bytes = bytes_fd.getvalue()

    manifest_entries = []
    for rel in reversed(scaler_releases):
        log.crit(f"Packaging optiscaler {rel['tag_name']}")
        try:
            scaler_resp = requests.get(
                rel["assets"][0]["browser_download_url"], timeout=10
            )
        except requests.exceptions.Timeout:
            continue

        src_path = config.paths.sources.joinpath(f"optiscaler_{rel['tag_name']}")
        src_path.mkdir(parents=True, exist_ok=True)
        with io.BytesIO(scaler_resp.content) as bytes_fd:
            with py7zr.SevenZipFile(bytes_fd) as archive_fd:
                names = archive_fd.getnames()
                wanted = [n for n in names if n in _package_files]
                log.crit(f"Found wanted files: {wanted}")
            archive = src_path.with_name(f"optiscaler_{rel['tag_name']}.7z")
            with archive.open("wb") as file_fd:
                file_fd.write(bytes_fd.getvalue())
        ec = subprocess.call(
            ["7z", "e", "-y", f"-o{str(src_path)}", str(archive), *wanted],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        os.makedirs(src_path.joinpath("plugins"), exist_ok=True)
        patcher = src_path.joinpath("plugins", "OptiPatcher.asi")
        with patcher.open("wb") as patcher_fd:
            patcher_fd.write(patcher_bytes)

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
        optiscaler_configs = (
            ((("Libraries", "OptiDllPath"),), "c:\\windows\\system32\\umu"),
            ((("FSR", "Fsr4Update"),), "true"),
            ((("Hotfix", "CheckForUpdate"),), "false"),
            (
                (("ProcessFilter", "ProcessExclusionList"),),
                "|".join(_excluded_processes),
            ),
        )
        for cfg in optiscaler_configs:
            combo, value = cfg
            cfg_found = False
            for section, option in combo:
                if ini.has_section(section):
                    if ini.has_option(section, option.lower()):
                        ini[section][option].value = value
                        cfg_found = True
            if not cfg_found:
                raise RuntimeError(
                    "OptiScaler: Could not edit config in version %s", rel["tag_name"]
                )
        ini.update_file(validate=True)

        # Create archive
        md5_hash = {}
        for root, dirs, files in src_path.walk():
            for file in files:
                # temporarily remove asi from checksums
                if file.endswith(".ini") or file.endswith(".asi"):
                    continue
                dll = Path(root).joinpath(file)
                with dll.open("rb") as dll_fd:
                    md5_hash[dll.relative_to(src_path).as_posix()] = hashlib.md5(dll_fd.read()).hexdigest().upper()

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

    scaler_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_scaler_version_url).path)).name
    )
    with scaler_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(scaler_releases[0]["tag_name"])

    patcher_version_file = config.paths.assets.joinpath(
        Path(unquote(urlparse(_patcher_version_url).path)).name
    )
    with patcher_version_file.open("w") as out_ver_fd:
        out_ver_fd.write(patcher_release["updated_at"])

    return {"optiscaler": manifest_entries}


if __name__ == "__main__":
    from pprint import pprint

    # _update, _ = check_optiscaler_update()
    # if _update:
    #     entries = package()
    #     pprint(entries)

    cached_file = Path("assets/optiscaler_v0.9.2.tar.xz")
    prefix_dir = Path("testing")
    prefix_dir.mkdir()
    path = prefix_dir.joinpath("second")
    path.mkdir()
    with tarfile.open(cached_file, 'r:xz') as tar_fd:
        names = tar_fd.getnames()
        for name in names:
            local_file = os.path.join(prefix_dir, path, name)
            if name.endswith('.ini') and os.path.exists(local_file):
                os.rename(local_file, local_file + '.old' )
            tar_fd.extract(name, os.path.join(prefix_dir, path), filter='data')


__all__ = ["check_optiscaler_update", "package"]
