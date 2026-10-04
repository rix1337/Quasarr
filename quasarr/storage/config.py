# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
"""Config wrapper for Quasarr.ini.

Locking contract:
- Write paths (__init__, save, delete, prune_unsupported_keys) take
  the module-level `lock`. `__init__` is locked because it can write
  defaults when a section is missing.
- get() is unlocked and reads from `self.__config__`, the snapshot
  loaded at __init__ time. Concurrent writes by other processes are
  not visible to long-lived Config instances; construct fresh
  instances per logical operation if cross-process freshness matters.
- Lock order: the config lock may be held while acquiring the
  database lock (via `_get_encryption_params` -> `DataBase`). Never
  the reverse. See `sqlite_database.py`.
- Methods that mutate `self._config` from disk must replace it with a
  fresh `RawConfigParser()` before reading; `configparser.read()`
  merges rather than replaces, so deletions by other processes would
  otherwise be reverted on writeback.
- All ini writes go through `_write_ini_atomically` (temp file +
  `os.replace`). The lock serializes read-modify-write between
  processes; the atomic replace guarantees no observer, including a
  process killed mid-write or a reader outside the lock, ever sees a
  truncated Quasarr.ini.
"""

import base64
import configparser
import contextlib
import os
import re
import shutil
import string
import tempfile

from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
from Cryptodome.Util.Padding import pad

from quasarr.providers import shared_state
from quasarr.providers.log import error, info, warn
from quasarr.search.sources.helpers import get_hostnames
from quasarr.storage.lock import get_lock, with_lock
from quasarr.storage.sqlite_database import DataBase

lock = get_lock("config")


def _write_ini_atomically(configfile, config):
    """Replace the ini in one step instead of truncating it in place.

    `open(path, "w")` empties the file before the new content lands, so a
    process killed inside that window leaves a truncated Quasarr.ini and any
    reader outside the file lock can observe one. Writing to a sibling temp
    file and `os.replace()`-ing it in guarantees every observer sees either
    the complete old or the complete new file; the file lock still serializes
    the read-modify-write itself.
    """
    directory = os.path.dirname(os.path.abspath(configfile))
    fd, tmp_path = tempfile.mkstemp(prefix=".Quasarr.ini.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_path, os.stat(configfile).st_mode)
        except OSError:
            pass  # first write: no existing file to copy permissions from
        os.replace(tmp_path, configfile)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


class Config(object):
    _DEFAULT_CONFIG = {
        "API": [
            ("key", "secret", ""),
        ],
        "JDownloader": [
            ("user", "secret", ""),
            ("password", "secret", ""),
            ("device", "str", ""),
        ],
        "Settings": [
            ("hostnames_url", "secret", ""),
        ],
        "Hostnames": [(hostname, "secret", "") for hostname in get_hostnames()],
        "FlareSolverr": [
            ("url", "str", ""),
        ],
        "Radarr": [
            ("url", "str", ""),
            ("api_key", "secret", ""),
        ],
        "Sonarr": [
            ("url", "str", ""),
            ("api_key", "secret", ""),
        ],
        "Notifications": [
            ("discord_webhook", "secret", ""),
            ("telegram_bot_token", "secret", ""),
            ("telegram_chat_id", "secret", ""),
            ("pushover_api_token", "secret", ""),
            ("pushover_user_key", "secret", ""),
        ],
        "AL": [("user", "secret", ""), ("password", "secret", "")],
        "DD": [("user", "secret", ""), ("password", "secret", "")],
        "DL": [("user", "secret", ""), ("password", "secret", "")],
        "NX": [("user", "secret", ""), ("password", "secret", "")],
        "JUNKIES": [("user", "secret", ""), ("password", "secret", "")],
    }
    __config__ = []

    @with_lock(lock)
    def __init__(self, section):
        self._configfile = shared_state.values["configfile"]
        self._section = section
        self._config = configparser.RawConfigParser()

        try:
            self._config.read(self._configfile)
            self._config.has_section(self._section) or self._set_default_config(
                self._section
            )
            self.__config__ = self._read_config(self._section)
        except configparser.DuplicateSectionError:
            print("Duplicate Section in Config File")
            raise
        except Exception as e:
            print(f"Unknown error while reading config file: {e}")
            raise

    def _set_default_config(self, section):
        self._config.add_section(section)
        for key, _key_type, value in self._DEFAULT_CONFIG[section]:
            self._config.set(section, key, value)

        _write_ini_atomically(self._configfile, self._config)

    @classmethod
    def _get_supported_keys(cls, section):
        return {
            key.lower()
            for key, _key_type, _value in cls._DEFAULT_CONFIG.get(section, [])
        }

    @classmethod
    def _build_unsupported_key_plan(cls, config):
        prune_plan = {}
        for section in config.sections():
            supported_keys = cls._get_supported_keys(section)
            if not supported_keys:
                continue

            unsupported_keys = sorted(
                key
                for key in config.options(section)
                if key.lower() not in supported_keys
            )
            if unsupported_keys:
                prune_plan[section] = unsupported_keys

        return prune_plan

    @classmethod
    @with_lock(lock)
    def prune_unsupported_keys(cls, configfile):
        config = configparser.RawConfigParser()

        config.read(configfile)

        prune_plan = cls._build_unsupported_key_plan(config)
        if not prune_plan:
            return {}

        backupfile = f"{configfile}.bak"
        try:
            shutil.copy2(configfile, backupfile)
        except Exception as e:
            warn(
                f'Unsupported INI key cleanup skipped: could not create backup "{backupfile}": {e}'
            )
            return {}

        for section, keys in prune_plan.items():
            for key in keys:
                config.remove_option(section, key)

        try:
            _write_ini_atomically(configfile, config)

            verify_config = configparser.RawConfigParser()
            verify_config.read(configfile)
            for section, keys in prune_plan.items():
                if not verify_config.has_section(section):
                    raise ValueError(f'Missing section "{section}" after cleanup')
                if any(verify_config.has_option(section, key) for key in keys):
                    raise ValueError(
                        f'Unsupported keys remain in "{section}" after cleanup'
                    )
        except Exception as e:
            shutil.copy2(backupfile, configfile)
            warn(
                f"Unsupported INI key cleanup failed verification and was reverted: {e}"
            )
            return {}

        removed_count = sum(len(keys) for keys in prune_plan.values())
        info(
            f"Pruned {removed_count} unsupported INI key{'s' if removed_count != 1 else ''}. "
            f'Backup saved to "{backupfile}".'
        )
        return prune_plan

    def _get_encryption_params(self):
        secrets = DataBase("secrets")
        crypt_key = secrets.retrieve("key")
        crypt_iv = secrets.retrieve("iv")
        if crypt_iv and crypt_key:
            return base64.b64decode(crypt_key), base64.b64decode(crypt_iv)
        else:
            crypt_key = get_random_bytes(32)
            crypt_iv = get_random_bytes(16)
            secrets.update_store("key", base64.b64encode(crypt_key).decode())
            secrets.update_store("iv", base64.b64encode(crypt_iv).decode())
            return crypt_key, crypt_iv

    def _set_to_config(self, section, key, value):
        # Re-sync under outer lock. configparser.read() merges into the
        # existing parser, so keys removed by other processes would survive
        # in memory and get revived on writeback. Use a fresh parser.
        self._config = configparser.RawConfigParser()
        self._config.read(self._configfile)
        default_value_type = [
            param[1] for param in self._DEFAULT_CONFIG[section] if param[0] == key
        ]
        if default_value_type and default_value_type[0] == "secret" and len(value):
            crypt_key, crypt_iv = self._get_encryption_params()
            cipher = AES.new(crypt_key, AES.MODE_CBC, crypt_iv)
            value = base64.b64encode(
                cipher.encrypt(pad(value.encode(), AES.block_size))
            )
            value = "secret|" + value.decode()
        self._config.set(section, key, value)
        self._write_config()

    def _read_config(self, section):
        return [
            (key, "", self._config.get(section, key))
            for key in self._config.options(section)
        ]

    def _write_config(self):
        _write_ini_atomically(self._configfile, self._config)

    def _get_from_config(self, scope, key):
        res = [param[2] for param in scope if param[0] == key]
        if not res:
            res = [
                param[2]
                for param in self._DEFAULT_CONFIG[self._section]
                if param[0] == key
            ]
        if [
            param
            for param in self._DEFAULT_CONFIG[self._section]
            if param[0] == key and param[1] == "secret"
        ]:
            value = res[0].strip("'\"")
            if value.startswith("secret|"):
                crypt_key, crypt_iv = self._get_encryption_params()
                cipher = AES.new(crypt_key, AES.MODE_CBC, crypt_iv)
                try:
                    decrypted_payload = (
                        cipher.decrypt(base64.b64decode(value[7:]))
                        .decode("utf-8")
                        .strip()
                    )
                except Exception as e:
                    # The key lives in Quasarr.db, so an ini restored without its
                    # matching database decrypts to garbage. Report it as unset
                    # instead of raising: setup then asks for the value again,
                    # rather than the process dying in the Docker restart loop.
                    # The stored ciphertext is left untouched so restoring the
                    # right Quasarr.db still recovers the value.
                    error(
                        f'Could not decrypt "{key}" in section "{self._section}" of Quasarr.ini: {e}. '
                        "It was encrypted with a different Quasarr.db. Restore the Quasarr.db that "
                        "belongs to this Quasarr.ini, or set the value again in the Web UI."
                    )
                    return ""
                final_payload = "".join(
                    filter(lambda c: c in string.printable, decrypted_payload)
                )
                return final_payload
            else:  ## Loaded value is not encrypted, return as is
                if len(value) > 0:
                    self.save(key, value)
                return value
        elif [
            param
            for param in self._DEFAULT_CONFIG[self._section]
            if param[0] == key and param[1] == "bool"
        ]:
            return True if len(res) and res[0].strip("'\"").lower() == "true" else False
        else:
            return res[0].strip("'\"") if len(res) > 0 else False

    @with_lock(lock)
    def save(self, key, value):
        self._set_to_config(self._section, key, value)
        self.__config__ = self._read_config(self._section)
        return

    @with_lock(lock)
    def get(self, key):
        self.__config__ = self._read_config(self._section)
        return self._get_from_config(self.__config__, key)

    @with_lock(lock)
    def delete(self, key):
        # Re-sync under outer lock. configparser.read() merges into the
        # existing parser, so keys removed by other processes would survive
        # in memory and get revived on writeback. Use a fresh parser.
        self._config = configparser.RawConfigParser()
        self._config.read(self._configfile)
        if self._config.has_option(self._section, key):
            self._config.remove_option(self._section, key)
            self._write_config()
            self.__config__ = self._read_config(self._section)
        return


def get_clean_hostnames(shared_state):
    hostnames = Config("Hostnames")
    set_hostnames = {}

    def clean_up_hostname(host, strg, hostnames):
        if strg and "/" in strg:
            strg = strg.replace("https://", "").replace("http://", "")
            strg = re.findall(r"([a-z-.]*\.[a-z]*)", strg)[0]
            hostnames.save(host, strg)
        if strg and re.match(r".*[A-Z].*", strg):
            hostnames.save(host, strg.lower())
        return strg

    for name in shared_state.values["sites"]:
        name = name.lower()
        hostname = clean_up_hostname(name, hostnames.get(name), hostnames)
        if hostname:
            set_hostnames[name] = hostname

    return set_hostnames
