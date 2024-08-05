# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

values = {}
lock = None
logger = None


def set_state(manager_dict, manager_lock):
    global values
    global lock
    values = manager_dict
    lock = manager_lock


def update(key, value):
    global values
    global lock
    lock.acquire()
    try:
        values[key] = value
    finally:
        lock.release()
