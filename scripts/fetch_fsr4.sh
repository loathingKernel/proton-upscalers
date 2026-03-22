#!/usr/bin/env bash
set -euo pipefail

# Extract amdxcffx64.dll (FSR4) from the latest AMD Adrenalin driver installer.
# This will help avoid issues in the future like we've experienced with the 4.1 leaks
# where AMD has decided to remove all DLLs beyond 4.0.0 from the download.amd.com URLs.
#
# Pull the full manifest from Pages so that a FSR4-only update
# still produces a complete deployment if there were no upstream changes to the manifest.

UPSCALERS_USER="${UPSCALERS_USER:?UPSCALERS_USER must be set}"
UPSCALERS_REPO="${UPSCALERS_REPO:?UPSCALERS_REPO must be set}"
REPO_URL="https://${UPSCALERS_USER}.github.io/${UPSCALERS_REPO#*/}"

AMD_REFERER="https://www.amd.com/en/support/download/drivers.html"
AMD_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/130.0"

adrenalin_url() {
    echo "https://drivers.amd.com/drivers/whql-amd-software-adrenalin-edition-${1}-win11-b.exe"
}

find_latest_version() {
    local page ver
    page=$(curl -s --max-time 15 -H "User-Agent: ${AMD_UA}" "${AMD_REFERER}" 2>/dev/null)
    ver=$(echo "$page" | grep -oP 'edition-\K[0-9]+\.[0-9]+\.[0-9]+(?=-minimalsetup)' | head -1)
    if [[ -n "$ver" ]]; then echo "$ver"; return; fi

    echo "could not scrape AMD download page, falling back to published version" >&2
    jq -re '.fsr4[0].internal_name // empty' assets/manifest.json 2>/dev/null \
        | grep -oP '[0-9]+\.[0-9]+\.[0-9]+'
}

get_published_version() {
    jq -re '.fsr4[0].internal_name // empty' assets/manifest.json 2>/dev/null \
        | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' || return 1
}

# If the Python step skipped, assets/manifest.json won't exist.
# Pull the full manifest and all referenced .xz assets from Pages.
ensure_manifest() {
    [[ -f assets/manifest.json ]] && return
    echo "assets/manifest.json missing, fetching from Pages" >&2
    mkdir -p assets
    curl -sf --max-time 10 -o assets/manifest.json "${REPO_URL}/manifest.json" || {
        echo "could not fetch manifest from Pages" >&2
        return 1
    }
    local url name
    for url in $(jq -r '.. | .download_url? // empty' assets/manifest.json 2>/dev/null | sort -u); do
        name=$(basename "$url")
        [[ -f "assets/${name}" ]] && continue
        echo "restoring ${name}" >&2
        curl -sf --max-time 120 -o "assets/${name}" "$url" || echo "warning: failed to restore ${name}" >&2
    done
}

restore_fsr4() {
    local fsr4
    fsr4=$(jq -e '.fsr4' assets/manifest.json 2>/dev/null) || return 1

    local xz_url
    xz_url=$(echo "$fsr4" | jq -r '.[0].download_url')
    curl -sf --max-time 60 -o "assets/$(basename "$xz_url")" "$xz_url" || return 1
    echo "restored existing FSR4 entry" >&2
}

fetch_and_extract() {
    local version="$1"
    WORKDIR=$(mktemp -d)
    trap 'rm -rf "$WORKDIR"' EXIT

    local installer="${WORKDIR}/adrenalin.exe"
    curl -L -H "Referer: ${AMD_REFERER}" -H "User-Agent: ${AMD_UA}" \
        --max-time 600 -o "$installer" "$(adrenalin_url "$version")"
    echo "downloaded $(( $(stat -c%s "$installer") / 1048576 )) MB" >&2

    local dll_path
    dll_path=$(7z l "$installer" 2>/dev/null | grep -oP '\S+amdxcffx64\.dll' | head -1)
    [[ -z "$dll_path" ]] && { echo "amdxcffx64.dll not found in archive" >&2; return 1; }

    7z x "$installer" -o"${WORKDIR}/extract" "$dll_path" -y >/dev/null 2>&1
    local extracted="${WORKDIR}/extract/${dll_path}"
    [[ -f "$extracted" ]] || { echo "extraction failed" >&2; return 1; }
    rm -f "$installer"

    local dll_size dll_md5 fsr_version
    dll_size=$(stat -c%s "$extracted")
    dll_md5=$(md5sum "$extracted" | awk '{print toupper($1)}')
    fsr_version=$(strings "$extracted" \
        | grep -oP '^4\.\d+\.\d+$' \
        | sort -t. -k1,1n -k2,2n -k3,3n \
        | tail -1)
    [[ -z "$fsr_version" ]] && { echo "could not detect FSR version" >&2; return 1; }

    local xz_name="amdxcffx64_v${fsr_version}_${version}.xz"
    xz -9 --stdout "$extracted" > "assets/${xz_name}"

    local xz_size xz_md5
    xz_size=$(stat -c%s "assets/${xz_name}")
    xz_md5=$(md5sum "assets/${xz_name}" | awk '{print toupper($1)}')
    echo "fsr ${fsr_version}: ${dll_size} -> ${xz_size} bytes" >&2

    local new_entry
    new_entry=$(cat <<EOF
{
  "version": "${fsr_version}",
  "version_number": 0,
  "internal_name": "Adrenalin ${version}",
  "internal_name_extra": "",
  "additional_label": "From AMD Adrenalin ${version}",
  "md5_hash": "${dll_md5}",
  "zip_md5_hash": "${xz_md5}",
  "download_url": "${REPO_URL}/${xz_name}",
  "file_description": "AMD FidelityFX Super Resolution 4",
  "signed_datetime": "",
  "is_signature_valid": false,
  "is_dev_file": false,
  "file_size": ${dll_size},
  "zip_file_size": ${xz_size},
  "dll_source": "AMD Adrenalin ${version}"
}
EOF
    )

    # Append to existing entries, keep last 7
    jq --argjson entry "$new_entry" \
        '.fsr4 = ((.fsr4 // []) + [$entry] | .[-7:])' \
        assets/manifest.json > assets/manifest.json.tmp
    mv assets/manifest.json.tmp assets/manifest.json
    echo "published FSR ${fsr_version} from Adrenalin ${version}" >&2
}

main() {
    ensure_manifest || { echo "no manifest available" >&2; return 1; }

    local latest published
    latest=$(find_latest_version)
    published=$(get_published_version 2>/dev/null || echo "")
    echo "latest: ${latest}, published: ${published:-none}" >&2

    if [[ "$latest" == "$published" ]]; then
        echo "FSR4 up to date" >&2
        restore_fsr4
        return 0
    fi

    echo "new Adrenalin ${latest} (was ${published:-none})" >&2
    fetch_and_extract "$latest"
}

main "$@"
