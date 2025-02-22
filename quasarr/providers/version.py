# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re


def get_version():
    return "1.0.8"


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
