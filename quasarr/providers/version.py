# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests


def get_version():
    return "2.2.0"


def get_latest_version():
    """
    Query GitHub API for the latest release of the Quasarr repository.
    Returns the tag name string (e.g. "1.5.0" or "1.4.2a1").
    Raises RuntimeError on HTTP errors.
    """
    api_url = "https://api.github.com/repos/rix1337/Quasarr/releases/latest"
    resp = requests.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API error: {resp.status_code} {resp.text}")
    data = resp.json()
    tag = data.get("tag_name") or data.get("name")
    if not tag:
        raise RuntimeError("Could not find tag_name in GitHub response")
    return tag


def _version_key(v):
    """
    Normalize a version string into a tuple for comparisons.
    E.g. "1.4.2a3" -> (1, 4, 2, 'a', 3), "1.4.2" -> (1, 4, 2, '', 0)
    """
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*)([a-z]?)([0-9]*)$", v)
    if not m:
        clean = re.sub(r"[^\d.]", "", v)
        parts = clean.split(".")
        nums = tuple(int(x) for x in parts if x.isdigit())
        return nums + ("", 0)
    base, alpha, num = m.groups()
    nums = tuple(int(x) for x in base.split("."))
    suffix_num = int(num) if num.isdigit() else 0
    return nums + (alpha or "", suffix_num)


def is_newer(latest, current):
    """
    Return True if latest > current using semantic+alpha comparison.
    """
    return _version_key(latest) > _version_key(current)


def newer_version_available():
    """
    Check local vs. GitHub latest version.
    Returns the latest version string if a newer release is available,
    otherwise returns None.
    """
    try:
        current = get_version()
        latest = get_latest_version()
    except:
        raise
    if is_newer(latest, current):
        return latest
    return None


def create_version_file():
    version = get_version()
    version_clean = re.sub(r'[^\d.]', '', version)
    if "a" in version:
        suffix = version.split("a")[1]
    else:
        suffix = 0
    version_split = version_clean.split(".")
    version_info = [
        "VSVersionInfo(",
        "  ffi=FixedFileInfo(",
        "    filevers=(" + str(int(version_split[0])) + ", " + str(int(version_split[1])) + ", " + str(
            int(version_split[2])) + ", " + str(int(suffix)) + "),",
        "    prodvers=(" + str(int(version_split[0])) + ", " + str(int(version_split[1])) + ", " + str(
            int(version_split[2])) + ", " + str(int(suffix)) + "),",
        "    mask=0x3f,",
        "    flags=0x0,",
        "    OS=0x4,",
        "    fileType=0x1,",
        "    subtype=0x0,",
        "    date=(0, 0)",
        "    ),",
        "  kids=[",
        "    StringFileInfo(",
        "      [",
        "      StringTable(",
        "        u'040704b0',",
        "        [StringStruct(u'CompanyName', u'RiX'),",
        "        StringStruct(u'FileDescription', u'Quasarr'),",
        "        StringStruct(u'FileVersion', u'" + str(int(version_split[0])) + "." + str(
            int(version_split[1])) + "." + str(int(version_split[2])) + "." + str(int(suffix)) + "'),",
        "        StringStruct(u'InternalName', u'Quasarr'),",
        "        StringStruct(u'LegalCopyright', u'Copyright © RiX'),",
        "        StringStruct(u'OriginalFilename', u'Quasarr.exe'),",
        "        StringStruct(u'ProductName', u'Quasarr'),",
        "        StringStruct(u'ProductVersion', u'" + str(int(version_split[0])) + "." + str(
            int(version_split[1])) + "." + str(int(version_split[2])) + "." + str(int(suffix)) + "')])",
        "      ]),",
        "    VarFileInfo([VarStruct(u'Translation', [1031, 1200])])",
        "  ]",
        ")"
    ]
    print("\n".join(version_info), file=open('file_version_info.txt', 'w', encoding='utf-8'))


if __name__ == '__main__':
    print(get_version())
    create_version_file()
