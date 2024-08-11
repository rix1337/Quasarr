# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import sqlite3
import time

from quasarr.providers import shared_state


def get_first(iterable):
    return iterable and list(iterable[:1]).pop() or None

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [row[0] for row in cursor.fetchall()]

    tables_to_drop = set(table_names) - set(keep_tables)

    for table in tables_to_drop:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        print(f"Entferne überflüssige Tabelle '{table}' aus der Datenbank.")

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()


class DataBase(object):
    def __init__(self, table):
        try:
            self._conn = sqlite3.connect(shared_state.values["dbfile"], check_same_thread=False, timeout=5)
            self._table = table
            if not self._conn.execute(
                    f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{self._table}';").fetchall():
                self._conn.execute(f"CREATE TABLE {self._table} (key, value)")
                self._conn.commit()
        except sqlite3.OperationalError as e:
            try:
                shared_state.logger.debug(
                    "Fehler bei Zugriff auf Quasarr.db: " + str(e) + " (neuer Versuch in 5 Sekunden).")
                time.sleep(5)
                self._conn = sqlite3.connect(shared_state.values["dbfile"], check_same_thread=False, timeout=10)
                self._table = table
                if not self._conn.execute(
                        f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{self._table}';").fetchall():
                    self._conn.execute(f"CREATE TABLE {self._table} (key, value)")
                    self._conn.commit()
                    shared_state.logger.debug("Zugriff auf Quasarr.db nach Wartezeit war erfolgreich.")
            except sqlite3.OperationalError as e:
                print("Fehler bei Zugriff auf Quasarr.db: ", str(e))

    def retrieve(self, key):
        query = f"SELECT value FROM {self._table} WHERE key=?"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        res = self._conn.execute(query, (key,)).fetchone()
        return res[0] if res else None

    def retrieve_all(self, key):
        query = f"SELECT distinct value FROM {self._table} WHERE key=? ORDER BY value"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        res = self._conn.execute(query, (key,))
        items = [str(r[0]) for r in res]
        return items

    def retrieve_all_titles(self):
        query = f"SELECT distinct key, value FROM {self._table} ORDER BY key"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        res = self._conn.execute(query)
        items = [[str(r[0]), str(r[1])] for r in res]
        return items if items else None

    def store(self, key, value):
        query = f"INSERT INTO {self._table} VALUES (?, ?)"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        self._conn.execute(query, (key, value))
        self._conn.commit()

    def update_store(self, key, value):
        delete_query = f"DELETE FROM {self._table} WHERE key=?"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        self._conn.execute(delete_query, (key,))
        insert_query = f"INSERT INTO {self._table} VALUES (?, ?)"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        self._conn.execute(insert_query, (key, value))
        self._conn.commit()

    def delete(self, key):
        query = f"DELETE FROM {self._table} WHERE key=?"
        # using this parameterized query to prevent SQL injection, which requires a tuple as second argument
        self._conn.execute(query, (key,))
        self._conn.commit()

    def reset(self):
        self._conn.execute(f"DROP TABLE IF EXISTS {self._table}")
        self._conn.commit()
