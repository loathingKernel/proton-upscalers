import os
import sys
from functools import wraps
from pathlib import Path

github_user = os.environ.get("UPSCALERS_USER", "user")
github_repo = os.environ.get("UPSCALERS_REPO", "user/repo").split("/")[1]
github_event = os.environ.get("UPSCALERS_EVENT", "test")

repo_url = f"https://{github_user}.github.io/{github_repo}"


def version_tuple(version: str) -> tuple:
    try:
        _version = tuple(version.lstrip('v').split('.'))
        _version = tuple((int(s) for s in _version))
    except Exception as e:
        _version =  0, 0, 0
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


__all__ = ["github_event", "repo_url", "log", "config", "version_tuple"]