# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
from __future__ import annotations

import inspect
import os
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger
from wcwidth import wcswidth, wrap

if TYPE_CHECKING:
    from loguru import Message

from dotenv import load_dotenv

load_dotenv(override=True)

# To change the log format, modify the _format variable. It uses loguru's formatting syntax.
_format = "<d>{time:YYYY-MM-DDTHH:mm:ss}</d> <lvl>{level:5}</lvl>{extra[context]}<b><M>{extra[source]}</M></b>{extra[padding]} {message}"
# The _context_max_width is used to calculate the padding for extra[context] based on the max amount of context emojis.
_context_max_width = wcswidth("⬜⬜⬜")

_subsequent_indent = 0
_loggers = {}

log_level_names = {
    50: "CRIT",
    40: "ERROR",
    30: "WARN",
    20: "INFO",
    10: "DEBUG",
    5: "TRACE",
}

# reverse map log_level_names
log_names_to_level = {v: k for k, v in log_level_names.items()}


def _read_env_log(key, default):
    try:
        try:
            level = log_names_to_level[os.getenv(key, default).upper()]
        except Exception:
            level = max(0, min(int(level), 50))
    except Exception:
        level = default

    return level


_log_level = _read_env_log("LOG", 20)

_context_replace = {
    "quasarr": "",  # /quasarr/*
    "arr": "☠️",  # /quasarr/arr/*
    "radarr": "🎬",  # /quasarr/storage/setup/radarr.py
    "radarr_api": "🎬",  # /quasarr/providers/radarr_api.py
    "sonarr": "📺",  # /quasarr/storage/setup/sonarr.py
    "sonarr_api": "📺",  # /quasarr/providers/sonarr_api.py
    "api": "🌐",  # /quasarr/api/*
    "lock": "🔓",  # /quasarr/storage/lock.py
    "captcha": "🧩",  # /quasarr/api/captcha/*
    "config": "⚙️",  # /quasarr/api/config/*
    "sponsors_helper": "💖",  # /quasarr/api/sponsors_helper/*
    "downloads": "📥",  # /quasarr/downloads/*
    "episode_links": "🎯",  # /quasarr/downloads/episode_links.py
    "linkcrypters": "🔐",  # /quasarr/linkcrypters/*
    "filecrypt": "🛡️",  # /quasarr/linkcrypters/filecrypt.py
    "hide": "👻",  # /quasarr/linkcrypters/hide.py
    "packages": "📦",  # /quasarr/api/packages/*
    "providers": "🔌",  # /quasarr/providers/*
    "html_templates": "🎨",  # /quasarr/providers/html_templates.py
    "imdb_metadata": "🎬",  # /quasarr/providers/imdb_metadata.py
    "xem_metadata": "📚",  # /quasarr/providers/xem_metadata.py
    "jd_cache": "📇",  # /quasarr/providers/jd_cache.py
    "log": "📝",  # /quasarr/providers/log.py
    "myjd_api": "🔑",  # /quasarr/providers/myjd_api.py
    "notifications": "🔔",  # /quasarr/providers/notifications.py
    "discord": "💬",  # /quasarr/providers/notifications/discord.py
    "telegram": "📱",  # /quasarr/providers/notifications/telegram.py
    "shared_state": "🧠",  # /quasarr/providers/shared_state.py
    "sessions": "🍪",  # /quasarr/providers/sessions/*
    "search": "🔍",  # /quasarr/search/*
    "storage": "💽",  # /quasarr/storage/*
    "categories": "🔠",  # /quasarr/storage/categories.py
    "setup": "🛠️",  # /quasarr/storage/setup/*
    "sqlite_database": "🗃️",  # /quasarr/storage/sqlite_database.py
    "sources": "🧲",  # /quasarr/*/sources/*
    "utils": "🧰",  # /quasarr/providers/utils.py
}


def _contexts_to_str(contexts: list[str]) -> str:
    source = ""
    if len(contexts) == 0:
        return "", source

    if contexts:
        if contexts[-1].__len__() == 2:
            source = contexts.pop()
        elif contexts[0] == "quasarr" and contexts.__len__() == 1:
            return "🌌", source

    return "".join(_context_replace.get(c, c) for c in contexts), source.upper()


def get_log_level_name(level: int = _log_level) -> str:
    return log_level_names[level]


def get_log_level(contexts: list[str] | None = None) -> int:
    if contexts is None:
        contexts = []
    level = _log_level

    for context in contexts:
        context_level = _read_env_log(
            "LOG" + f"_{context.upper()}" if context else "", _log_level
        )
        if context_level < level:
            level = context_level

    return level


class _Logger:
    def __init__(self, contexts: list[str] | None = None):
        if contexts is None:
            contexts = []
        self.level = get_log_level(contexts)
        context, source = _contexts_to_str(contexts)
        width = wcswidth(context + source)
        padding = _context_max_width - width

        self.logger_alt = logger.bind(
            context=context,
            source=source,
            padding=" " * padding,
        )
        self.logger = self.logger_alt.opt(colors=True)

    def _log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        if self.level > level:
            return

        try:
            try:
                self.logger.log(log_level_names[level], msg, *args, **kwargs)
            except ValueError as e:
                # Fallback: try logging without color parsing if tags are mismatched
                self.logger_alt.log(log_level_names[level], msg, *args, **kwargs)

                if self.level <= 10:
                    self.logger_alt.debug(
                        f"Log formatting error: {e} | Original message: {msg}"
                    )
        except Exception:
            # Fallback: just print to stderr if logging fails completely
            print(f"LOGGING FAILURE: {msg}", file=sys.stderr)

    def crit(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(50, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(40, msg, *args, **kwargs)

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(30, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(20, msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(10, msg, *args, **kwargs)

    def trace(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(5, msg, *args, **kwargs)


def get_logger(context: str) -> _Logger:
    if context not in _loggers:
        _loggers[context] = _Logger(context.split(".") if context else [])
    return _loggers[context]


def _get_logger_for_module() -> _Logger:
    # get the calling module filename
    frame = inspect.currentframe()
    caller_frame = frame.f_back.f_back
    module_name = caller_frame.f_globals["__name__"]

    return get_logger(module_name)


def get_source_logger(source: str) -> _Logger:
    # get the calling module filename
    frame = inspect.currentframe()
    caller_frame = frame.f_back.f_back
    module_name = caller_frame.f_globals["__name__"]

    module_name += f".{source}"
    return get_logger(module_name)


def crit(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().crit(msg, *args, **kwargs)


def error(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().error(msg, *args, **kwargs)


def warn(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().warn(msg, *args, **kwargs)


def info(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().info(msg, *args, **kwargs)


def debug(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().debug(msg, *args, **kwargs)


def trace(msg: str, *args: Any, **kwargs: Any) -> None:
    _get_logger_for_module().trace(msg, *args, **kwargs)


def get_log_max_width() -> int:
    try:
        return int(os.getenv("LOG_MAX_WIDTH"))
    except Exception:
        pass
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 160


def _wrapping_sink(message: Message) -> None:
    wrapped = wrap(
        text=message,
        width=get_log_max_width(),
        subsequent_indent=_subsequent_indent * " ",
    )
    for w in wrapped:
        sys.stdout.write(w + "\n")


def _counting_sink(message: Message) -> None:
    message = message.strip()[:-1]
    global _subsequent_indent
    _subsequent_indent = message.__len__()


def _init():
    logger.level(name="WARN", no=30, color="<yellow>")
    logger.level(name="CRIT", no=50, color="<red>")

    logger.remove(0)
    _c = logger.add(
        _counting_sink,
        format=_format,
        level=50,
    )
    _Logger().crit("!")
    logger.remove(_c)
    logger.add(
        _wrapping_sink,
        format=_format,
        colorize=os.getenv("LOG_COLOR", "1").lower() in ["1", "true", "yes"],
        level=5,
    )
    trace("Initialized logger with subsequent indent of " + str(_subsequent_indent))


_init()
