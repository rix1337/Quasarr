# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import os


def timestamp():
    return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def info(string):
    print(f"{timestamp()} {string}")


def debug(string):
    if os.getenv('DEBUG'):
        info(string)
