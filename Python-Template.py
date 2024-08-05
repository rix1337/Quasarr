# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import multiprocessing

from quasarr import run

if __name__ == '__main__':
    multiprocessing.freeze_support()
    run.main()
