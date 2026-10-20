"""Durable commendations, separate from replaceable profile snapshots."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

MAX_COUNT = 0x7fffffff  # Native signed counter representation, not a battle-click quota.
CHARACTERS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 20, 21}


def database_path():
    return Path(os.environ.get('ROI_COMMENDATION_DB',
                              str(Path(__file__).with_name('commendations.sqlite3'))))


@contextmanager
def database():
    path = database_path()
    connection = sqlite3.connect(path, timeout=3)
    try:
        connection.execute('PRAGMA max_page_count=16384')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('CREATE TABLE IF NOT EXISTS totals '
                           '(uid TEXT, cid INTEGER, count INTEGER NOT NULL, PRIMARY KEY(uid,cid))')
        connection.execute('CREATE TABLE IF NOT EXISTS receipts '
                           '(round TEXT PRIMARY KEY, target TEXT, cid INTEGER, count INTEGER NOT NULL)')
        yield connection
    finally:
        connection.close()


def award(round_id, uid, cid, before, amount):
    if (not isinstance(round_id, str) or len(round_id) != 32
            or type(uid) is not int or not 0 < uid < 2**64 or cid not in CHARACTERS
            or type(before) is not int or type(amount) is not int
            or before < 0 or amount <= 0 or before + amount > MAX_COUNT):
        raise ValueError('Invalid commendation')
    with database() as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            receipt = db.execute('SELECT target,cid,count FROM receipts WHERE round=?',
                                 (round_id,)).fetchone()
            previous = receipt[2] if receipt else 0
            if receipt and receipt[:2] != (str(uid), cid):
                raise ValueError('Commendation target changed')
            if before > previous or before < previous < before + amount:
                raise ValueError('Noncontiguous commendation count')
            if before + amount <= previous:
                return 0
            combined = db.execute('SELECT COALESCE(SUM(count),0) FROM totals WHERE uid=?',
                                  (str(uid),)).fetchone()[0]
            if combined + amount > MAX_COUNT:
                raise ValueError('Native combined count range exceeded')
            total = db.execute('SELECT count FROM totals WHERE uid=? AND cid=?',
                               (str(uid), cid)).fetchone()
            total = (total[0] if total else 0) + amount
            if total > MAX_COUNT:
                raise ValueError('Native count range exceeded')
            db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?,?,?)',
                       (round_id, str(uid), cid, before + amount))
            db.execute('INSERT OR REPLACE INTO totals VALUES (?,?,?)', (str(uid), cid, total))
            return amount


def totals(uid):
    if not database_path().exists():
        return {}
    with database() as db:
        rows = db.execute('SELECT cid,count FROM totals WHERE uid=?', (str(uid),)).fetchall()
    return {str(cid): count for cid, count in rows}
