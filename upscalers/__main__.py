import json
import sys

import upscalers.amdxcffx64 as amdxcffx64
import upscalers.dlss_swapper as dlss_swapper
import upscalers.fidelityfx as fidelityfx
import upscalers.optiscaler as optiscaler
from upscalers.common import github_event, log, config


def main() -> int:
    # if config.paths.sources.exists():
    #     shutil.rmtree(config.paths.sources)
    # if config.paths.assets.exists():
    #     shutil.rmtree(config.paths.assets)

    manfst, manfst_md5 = dlss_swapper.get_manifest()
    manfst.pop("known_dlls")

    if github_event == "schedule":
        update_dlss_swapper = dlss_swapper.check_update(manfst_md5)
        update_optiscaler, _ = optiscaler.check_optiscaler_update()
        update_optipatcher, _ = optiscaler.check_optipatcher_update()
        update_amdxcffx64_amd, _ = amdxcffx64.check_amd_update()
        update_amdxcffx64_proton, _ = amdxcffx64.check_proton_update()
        update_amdxcffx64 = update_amdxcffx64_amd or update_amdxcffx64_proton
        update_fidelityfx = (
            update_dlss_swapper or update_optiscaler or update_optipatcher or update_amdxcffx64
        )
    else:
        update_dlss_swapper = update_optiscaler = update_amdxcffx64 = update_fidelityfx = True

    if not any((update_dlss_swapper, update_optiscaler, update_amdxcffx64, update_fidelityfx)):
        log.crit("Nothing to do")
        return 1

    dlss_swapper.package(manfst, manfst_md5)

    optiscaler_entries = optiscaler.package()
    manfst.update(optiscaler_entries)

    fidelityfx_entries = fidelityfx.package()
    manfst.update(fidelityfx_entries)

    amdxcffx64_entries = amdxcffx64.package()
    manfst.update(amdxcffx64_entries)

    with config.paths.assets.joinpath("manifest.json").open("w") as out_man_fd:
        out_man_fd.write(json.dumps(manfst))

    return 0


if __name__ == "__main__":
    ec = main()
    sys.exit(ec)
