import functools
import os
import sys
import urllib.request
import urllib.error
from functools import wraps
from pathlib import Path

import requests
from orjson import orjson

github_user = os.environ.get("UPSCALERS_USER", "user")
github_repo = os.environ.get("UPSCALERS_REPO", "user/repo").split("/")[1]
github_event = os.environ.get("UPSCALERS_EVENT", "test")

repo_url = f"https://{github_user}.github.io/{github_repo}"


def version_tuple(version: str) -> tuple:
    try:
        _version = tuple(version.lstrip("v").split("."))
        _version = tuple((int(s) for s in _version))
    except Exception:
        _version = 0, 0, 0
    return _version


def ensure_dir_exists(func):
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


_entry_cwd = os.getcwd()


class Config:
    class Paths:
        @property
        @ensure_dir_exists
        def cache_dir(self) -> Path:
            return Path(_entry_cwd)

        @property
        @ensure_dir_exists
        def sources(self) -> Path:
            return self.cache_dir.joinpath("sources")

        @property
        @ensure_dir_exists
        def assets(self) -> Path:
            return self.cache_dir.joinpath("assets")

    paths = Paths()


log = Log()
config = Config()


@functools.cache
def get_github_releases(url: str) -> dict:
    try:
        resp = requests.get(url, timeout=5)
        data = resp.content.decode("utf-8")
        return orjson.loads(data)
    except requests.exceptions.Timeout:
        pass
    return {}


def check_github_update(releases_url: str, version_url: str, *, comparator: str = "tag") -> tuple[bool, str]:
    releases = get_github_releases(releases_url)
    if not releases:
        return False, ""
    release = releases[0]
    if comparator == "tag":
        remote_version = release["tag_name"]
    elif comparator == "date":
        remote_version = release["updated_at"]
    else:
        raise RuntimeError(f"Unknown comparator: {comparator}")
    try:
        with urllib.request.urlopen(version_url, timeout=10) as url_fd:
            local_version = url_fd.read().strip().decode("utf-8")
            if remote_version == local_version:
                log.crit("Local version is up to date.")
                return False, remote_version
    except urllib.error.HTTPError as e:
        log.crit(str(e))

    return True, remote_version


if __name__ == "__main__":
    check_github_update("https://api.github.com/repos/optiscaler/OptiPatcher/releases", "version_optipatcher.txt")


__all__ = [
    "github_event",
    "repo_url",
    "log",
    "config",
    "version_tuple",
    "get_github_releases",
    "check_github_update",
]
