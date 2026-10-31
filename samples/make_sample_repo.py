#!/usr/bin/env python3
"""Build `sundial`: a specimen repository with a real, dated git history.

The Last Commit needs a repository whose story can be *read out of the git
objects* — not one that is annotated with a story. This script writes the
files and then replays 40+ commits with backdated author/committer timestamps
so the timeline, the silence, the skipped test and the unmerged branch are all
genuine artefacts of the history.

The project is fictional. Every date, diff and TODO below is real inside the
generated repository, which is the only thing the archaeologist ever reads.

    python3 samples/make_sample_repo.py [--force]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "data" / "repos" / "sundial"

MIRA = ("Mira Kestrel", "mira@kestrel.invalid")
JAY = ("J. Alder", "jay@alder.invalid")

# --------------------------------------------------------------------------
# File contents. Each file is a list of "blocks"; a commit grows a file to N
# blocks, so the diffs are small and believable instead of one giant dump.
# --------------------------------------------------------------------------

README = [
    """# sundial

A time tracker that lives in your terminal. Start a session, forget it
exists, get an honest report at the end of the day.

```
$ sundial start "vector database post"
$ sundial stop
$ sundial totals
vector database post     1.42h
```
""",
    """
## Install

```
git clone https://example.invalid/mira/sundial
cd sundial
python3 setup.py install --user
```

Python 3.5+. Linux only for now. macOS probably works, I have not tried it.
""",
    """
## How it works

`sundial start` opens a row in a SQLite file under `~/.local/share/sundial`.
`sundial daemon` forks a watcher, which closes the session if the machine has
been idle for longer than `idle_minutes` (default 15).

Nothing is sent anywhere. There is no account, no sync, no telemetry. The
whole point is that it keeps working on a train.
""",
    """
## Roadmap

- [x] 0.1 — sessions and totals
- [x] 0.2 — sqlite storage
- [x] 0.3 — idle detection
- [ ] 0.4 — crash-safe sessions
- [ ] 0.5 — a day view that fits in 80 columns
""",
    """
## Status

0.3 is usable. 0.4 is where the interesting problems are: the watcher forks,
the database wants a write lock, and the two do not get along. See
[NOTES.md](NOTES.md) if you are curious how far I got.
""",
]

CHANGELOG = [
    """# Changelog

## 0.1.0 — 2017-03-12
- `start`, `stop`, `totals`
- sessions stored in sqlite
""",
    """
## 0.2.0 — 2017-04-15
- sessions survive a restart
- `report --month`
""",
    """
## 0.3.0 — 2017-05-20
- idle detection
- config file at `~/.config/sundial/config`
""",
    """
## 0.3.1 — 2017-06-18
- fix: `connect()` crashed when the database directory did not exist
""",
    """
## 0.3.2 — 2017-09-23
- `report --month` is 4x faster
""",
    """
## 0.4.0 — unreleased
- thread based watchdog (branch `wip/crash-safe`)
- crash-safe sessions: **not finished**
""",
]

STORAGE = [
    '''"""SQLite storage for sundial sessions."""

import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    label      TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER
);
"""
''',
    '''def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn
''',
    '''def start_session(conn, label):
    now = int(time.time())
    cur = conn.execute(
        "INSERT INTO sessions (label, started_at) VALUES (?, ?)", (label, now)
    )
    conn.commit()
    return cur.lastrowid
''',
    '''def stop_session(conn, session_id=None):
    now = int(time.time())
    if session_id is None:
        row = conn.execute(
            "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        session_id = row["id"]
    conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (now, session_id))
    conn.commit()
    return session_id
''',
    '''def totals(conn):
    rows = conn.execute(
        "SELECT label, started_at, ended_at FROM sessions"
    ).fetchall()
    out = {}
    for row in rows:
        out[row["label"]] = out.get(row["label"], 0) + (row["ended_at"] - row["started_at"])
    return out
''',
    '''def sessions_between(conn, start, end):
    return conn.execute(
        "SELECT * FROM sessions WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
        (start, end),
    ).fetchall()
''',
    '''def enable_wal(conn):
    # 2017-05-07: turned this on, then the forked watcher inherited the write
    # lock and every write blocked. Reverted in 8f2a1c4. See NOTES.md.
    # conn.execute("PRAGMA journal_mode=WAL")
    return conn
''',
]

DAEMON = [
    '''"""Background session watcher.

One loop, one job: if the machine has been idle for longer than the configured
threshold, close the open session so the report stays honest.
"""

import os
import signal
import sys
import time

from .config import load_config
from .storage import connect, start_session, stop_session

IDLE_THRESHOLD = 15 * 60
''',
    '''def begin(label):
    cfg = load_config()
    conn = connect(cfg["db_path"])
    return start_session(conn, label)


class Watch:
    def __init__(self, conn):
        self.conn = conn
        self.running = True

    def start(self):
        while self.running:
            time.sleep(30)
            if idle_seconds() > IDLE_THRESHOLD:
                stop_session(self.conn)
                self.running = False
''',
    '''def idle_seconds():
    # X11 only, via xprintidle(1). Wayland users are on their own for now.
    try:
        out = os.popen("xprintidle").read().strip()
        return int(out) / 1000.0
    except (OSError, ValueError):
        return 0.0
''',
    '''def fork_watcher(conn):
    pid = os.fork()
    if pid == 0:
        Watch(conn).start()
        os._exit(0)
    return pid
''',
    '''def main(argv=None):
    label = " ".join(argv or sys.argv[1:]) or "untitled"
    conn = connect(load_config()["db_path"])
    session_id = start_session(conn, label)
    watch = Watch(conn)

    def on_signal(signum, frame):
        # TODO: closing here still loses the last 30 seconds of the session,
        # because the watchdog loop only checks every 30 seconds.
        stop_session(conn, session_id)
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_signal)
    watch.start()
''',
]

CLI = [
    '''"""Command line entry point."""

import sys

from . import __version__
from .storage import connect, start_session, stop_session, totals

USAGE = """sundial 0.1
usage: sundial <command> [args]

  start <label>   start a session
  stop            stop the open session
  totals          time per label
"""
''',
    '''def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(USAGE)
        return 1
    cmd, rest = argv[0], argv[1:]
    conn = connect(_db_path())
    if cmd == "start":
        start_session(conn, " ".join(rest) or "untitled")
    elif cmd == "stop":
        stop_session(conn)
    elif cmd == "totals":
        for label, seconds in sorted(totals(conn).items()):
            print("{:<24} {:5.2f}h".format(label, seconds / 3600))
    else:
        print(USAGE)
        return 2
    return 0
''',
    '''def _db_path():
    from .config import load_config

    return load_config()["db_path"]


if __name__ == "__main__":
    sys.exit(main())
''',
]

REPORT = [
    '''"""Human readable reports."""

import time

from .storage import sessions_between
''',
    '''def day_bounds(day):
    """Return the unix range for a YYYY-MM-DD string, in local time."""
    start = time.mktime(time.strptime(day, "%Y-%m-%d"))
    return int(start), int(start + 86400)
''',
    '''def report_month(conn, month=None):
    month = month or time.strftime("%Y-%m")
    year, mon = (int(part) for part in month.split("-"))
    days = 31 if mon in (1, 3, 5, 7, 8, 10, 12) else 30
    rows = []
    for day in range(1, days + 1):
        start, end = day_bounds("{}-{:02d}".format(month, day))
        total = 0
        for session in conn.execute("SELECT * FROM sessions").fetchall():
            if start <= session["started_at"] < end:
                total += session["ended_at"] - session["started_at"]
        rows.append(("{}-{:02d}".format(month, day), total))
    return rows
''',
    '''def format_table(rows):
    lines = ["date         hours", "------------ -----"]
    for day, seconds in rows:
        if seconds:
            lines.append("{} {:5.2f}".format(day, seconds / 3600))
    return "\\n".join(lines)
''',
    '''def print_month(conn, month=None):
    # TODO: the 80 column day view is still a sketch in a notebook.
    print(format_table(report_month(conn, month)))
''',
]

CONFIG = [
    '''"""Config loading. One key = value file, parsed by hand because 2017."""

import os

DEFAULTS = {
    "db_path": os.path.expanduser("~/.local/share/sundial/sessions.db"),
    "idle_minutes": 15,
}
''',
    '''def load_config():
    cfg = dict(DEFAULTS)
    path = os.path.expanduser("~/.config/sundial/config")
    try:
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                # TODO: coerce idle_minutes to int. Right now the config file
                # is decorative: daemon.py hardcodes the threshold.
                cfg[key.strip()] = value.strip()
    except OSError:
        pass
    return cfg
''',
    '''def save_config(cfg):
    path = os.path.expanduser("~/.config/sundial/config")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        for key, value in cfg.items():
            handle.write("{} = {}\\n".format(key, value))
''',
]

TESTS = [
    '''import os
import tempfile

from sundial.storage import connect, start_session, stop_session, totals


def fresh_db():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    os.unlink(path)
    return connect(path)
''',
    '''def test_start_stop():
    conn = fresh_db()
    session_id = start_session(conn, "writing")
    stop_session(conn, session_id)
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["ended_at"] is not None
''',
    '''def test_totals():
    conn = fresh_db()
    first = start_session(conn, "reading")
    stop_session(conn, first)
    assert totals(conn)["reading"] >= 0
''',
    '''import pytest


@pytest.mark.skip(reason="recovery after a crash mid-write is not implemented yet")
def test_wal_recovery():
    conn = fresh_db()
    conn.execute("PRAGMA journal_mode=WAL")
    start_session(conn, "crash")
    # simulate a process that dies before committing
    assert totals(conn) == {}
''',
]

NOTES = [
    """# Notes to self

Loose ends, so that future me does not have to rediscover them.
""",
    """
## 2017-05-06 — WAL and fork()

Tried `PRAGMA journal_mode=WAL` in `enable_wal()` so `report` can read while
the daemon writes. It works, until the idle watcher forks: the child inherits
the write lock and every subsequent write blocks forever.

Turned it off again in 8f2a1c4. Storage stays in rollback journal until the
watcher stops forking.
""",
    """
## 2017-07-01 — report is slow

`report --month` takes 1.9s on 40k rows. It is the per-day loop in
`report.py`: 31 separate `sessions_between()` calls, each re-scanning the
table. Profile before touching it.
""",
    """
## 2018-01-19 — two ways out

1. Move idle detection into a thread, so the watcher stops forking, so WAL is
   safe. Needs a rewrite of `daemon.py`; the thread cannot interrupt
   `time.sleep(30)` on shutdown.
2. One connection per process, opened after the fork. Probably correct.
   Probably a weekend.

Branch `wip/crash-safe` has option 1 half done. It is not merged and it does
not work. If you are reading this: sorry.
""",
]

LOCK_PY = '''"""Cross-process lock for the watcher. Unfinished.

The idea was to take an flock() before a write and release it after, so that a
forked child could never inherit a half-open transaction. It deadlocks on the
second start in the same terminal, which is why this file never made it into
master.
"""

import fcntl
import os


class SessionLock:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a+")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        # TODO: this never gets called when the child exits via os._exit().
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
'''

SETUP = '''from setuptools import find_packages, setup

setup(
    name="sundial",
    version="{version}",
    description="A time tracker that lives in your terminal",
    author="Mira Kestrel",
    packages=find_packages(),
    entry_points={{"console_scripts": ["sundial=sundial.cli:main"]}},
    python_requires=">=3.5",
)
'''

INIT = '''"""sundial — a time tracker that lives in your terminal."""

__version__ = "{version}"
'''

GITIGNORE = """*.pyc
__pycache__/
build/
dist/
*.egg-info/
.venv/
sessions.db
"""

LICENSE = """MIT License

Copyright (c) 2017 Mira Kestrel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

BLOCKS = {
    "README.md": README,
    "CHANGELOG.md": CHANGELOG,
    "NOTES.md": NOTES,
    "sundial/storage.py": STORAGE,
    "sundial/daemon.py": DAEMON,
    "sundial/cli.py": CLI,
    "sundial/report.py": REPORT,
    "sundial/config.py": CONFIG,
    "tests/test_storage.py": TESTS,
}

VERSION = "0.1.0"


# --------------------------------------------------------------------------
# The history. (date, author, message, grow={path: block_count}, edits=[...])
# --------------------------------------------------------------------------

HISTORY = [
    ("2017-03-04T10:12:00", MIRA, "init: prove the idea", {"README.md": 1}),
    ("2017-03-04T21:47:00", MIRA, "first working timer",
     {"sundial/storage.py": 1}),
    ("2017-03-05T09:31:00", MIRA, "store sessions in sqlite instead of a csv",
     {"sundial/storage.py": 2, "sundial/config.py": 1, "sundial/cli.py": 1}),
    ("2017-03-05T22:05:00", MIRA, "start/stop actually persists now", {"sundial/storage.py": 3}),
    ("2017-03-08T19:40:00", MIRA, "README: show the usage, explain the shape",
     {"README.md": 2}),
    ("2017-03-11T14:22:00", MIRA, "stop the newest open session, not the oldest",
     {"sundial/storage.py": 4}),
    ("2017-03-12T11:03:00", MIRA, "totals, so the numbers leave the database",
     {"sundial/storage.py": 5}),
    ("2017-03-12T23:18:00", MIRA, "0.1.0", {"CHANGELOG.md": 1}),
    ("2017-03-18T16:55:00", MIRA, "print a table instead of raw rows", {"sundial/report.py": 1}),
    ("2017-03-19T10:30:00", MIRA, "report a whole month", {"sundial/report.py": 2}),
    ("2017-03-19T18:44:00", MIRA, "report --month, ugly but it runs", {"sundial/report.py": 3,
                                                                      "sundial/cli.py": 2}),
    ("2017-03-25T13:09:00", JAY, "fix crash when the db folder does not exist", {},
     [("sundial/storage.py",
       'def connect(path):\n    os.makedirs(os.path.dirname(path), exist_ok=True)\n',
       'def connect(path):\n    parent = os.path.dirname(path)\n    if parent:\n        os.makedirs(parent, exist_ok=True)\n')]),
    ("2017-03-26T20:12:00", MIRA, "idle detection via a forked watcher",
     {"sundial/daemon.py": 1, "sundial/config.py": 2}),
    ("2017-04-01T09:05:00", MIRA, "daemon: stop writing to stdout", {"sundial/daemon.py": 2}),
    ("2017-04-02T15:33:00", JAY, "README: the install instructions were wrong", {},
     [("README.md", "python3 setup.py install --user", "python3 setup.py install --user\n```\n\nOr, if you prefer pip:\n\n```\npip3 install --user .")]),
    ("2017-04-08T22:51:00", MIRA, "totals() was counting open sessions as zero", {},
     [("sundial/storage.py",
       '    for row in rows:\n        out[row["label"]]',
       '    for row in rows:\n        if row["ended_at"] is None:\n            continue\n        out[row["label"]]')]),
    ("2017-04-15T12:40:00", MIRA, "0.2: sessions survive a restart", {"CHANGELOG.md": 2}),
    ("2017-04-15T19:02:00", MIRA, "format_table()", {"sundial/report.py": 4}),
    ("2017-04-22T11:26:00", JAY, "handle Ctrl-C without a traceback", {},
     [("sundial/daemon.py",
       "        while self.running:\n            time.sleep(30)",
       "        while self.running:\n            try:\n                time.sleep(30)\n            except KeyboardInterrupt:\n                break")]),
    ("2017-04-29T18:15:00", MIRA, "bump version to 0.2.0", {}),
    ("2017-05-06T21:38:00", MIRA, "NOTES: the fork and WAL problem", {"NOTES.md": 2}),
    ("2017-05-07T10:44:00", MIRA, "try WAL, revert WAL", {"sundial/storage.py": 7}),
    ("2017-05-13T17:20:00", MIRA, "config file at ~/.config/sundial", {"sundial/config.py": 3}),
    ("2017-05-20T14:08:00", MIRA, "0.3: idle detection", {"sundial/daemon.py": 3,
                                                          "CHANGELOG.md": 3}),
    ("2017-05-27T09:59:00", MIRA, "README: explain how the watcher works", {"README.md": 4}),
    ("2017-06-03T20:41:00", MIRA, "clean up the help text", {"sundial/cli.py": 3}),
    ("2017-06-10T13:27:00", JAY, "tests: start/stop and totals", {"tests/test_storage.py": 3}),
    ("2017-06-17T16:11:00", MIRA, "add a LICENSE (MIT)", {}),
    ("2017-06-24T11:48:00", MIRA, "report: february is not 30 days", {},
     [("sundial/report.py",
       '    days = 31 if mon in (1, 3, 5, 7, 8, 10, 12) else 30',
       '    days = 31 if mon in (1, 3, 5, 7, 8, 10, 12) else 28 if mon == 2 else 30')]),
    ("2017-07-01T22:30:00", MIRA, "NOTES: report is slow, profile it first", {"NOTES.md": 3}),
    ("2017-09-02T18:04:00", MIRA, "0.3.1", {"CHANGELOG.md": 4}),
    ("2017-09-09T15:52:00", MIRA, "half finished WAL recovery test, skipping it for now",
     {"tests/test_storage.py": 4}),
    ("2017-09-10T10:16:00", MIRA, "storage: sessions_between()", {"sundial/storage.py": 6}),
    ("2017-09-16T21:07:00", MIRA, "report: stop scanning the table 31 times (1.9s -> 0.4s)",
     {"sundial/report.py": 5},
     [("sundial/report.py",
       '        for session in conn.execute("SELECT * FROM sessions").fetchall():\n            if start <= session["started_at"] < end:\n                total += session["ended_at"] - session["started_at"]',
       '        for session in sessions_between(conn, start, end):\n            total += session["ended_at"] - session["started_at"]')]),
    ("2017-09-23T12:33:00", MIRA, "0.3.2", {"CHANGELOG.md": 5}),
    ("2017-10-14T19:25:00", MIRA, "start the 0.4 work: signal handling", {"sundial/daemon.py": 5}),
    ("2017-10-28T23:41:00", MIRA, "TODO: SIGTERM still loses the last 30 seconds", {},
     [("sundial/daemon.py",
       'One loop, one job:',
       '# TODO: move idle detection into a thread so storage can use WAL.\n# Blocked since May. See NOTES.md.\n\nOne loop, one job:')]),
    ("2017-11-02T20:18:00", MIRA, "NOTES: the revert is 8f2a1c4", {},
     [("NOTES.md",
       'Turned it off again in 8f2a1c4.',
       'Turned it off again in 8f2a1c4. For whatever a commit hash is worth\nin a repository nobody reads.')]),
    ("2017-11-18T14:07:00", MIRA, "README: 0.4 is where the interesting problems are",
     {"README.md": 5}),
    ("2017-12-09T17:36:00", MIRA, "bump version to 0.4.0.dev0", {}),
    ("2017-12-28T10:02:00", MIRA, "remove an unused import", {},
     [("sundial/cli.py", "from . import __version__\n", "")]),
    ("2018-01-06T21:19:00", MIRA, "CHANGELOG: 0.4 progress", {"CHANGELOG.md": 6}),
    ("2018-01-19T22:04:00", MIRA, "NOTES: two ways out of the fork problem", {"NOTES.md": 4}),
    ("2018-01-20T13:44:00", MIRA, "sort the report by date, not by insertion order", {},
     [("sundial/report.py",
       '    for day, seconds in rows:',
       '    for day, seconds in sorted(rows):')]),
    ("2018-01-27T18:29:00", MIRA, "cli: add a status command", {},
     [("sundial/cli.py",
       '    elif cmd == "totals":',
       '    elif cmd == "status":\n        row = conn.execute(\n            "SELECT label FROM sessions WHERE ended_at IS NULL"\n        ).fetchone()\n        print("running: " + row["label"] if row else "idle")\n    elif cmd == "totals":'),
      ("sundial/cli.py",
       '  totals          time per label',
       '  status          is a session running?\n  totals          time per label')]),
    ("2018-02-03T16:58:00", MIRA, "tests: explain why wal recovery is skipped", {},
     [("tests/test_storage.py",
       'reason="recovery after a crash mid-write is not implemented yet"',
       'reason="recovery after a crash mid-write is not implemented; see NOTES.md"')]),
    ("2018-02-11T21:06:00", MIRA, "fix typo in --help output", {},
     [("sundial/cli.py",
       '  stop            stop the open session',
       '  stop            stop the current session'),
      ("sundial/cli.py",
       '  totals          time per label',
       '  totals          time per label\n  report          hours per day for the current month')]),
]

# The branch that never came back.
BRANCH = "wip/crash-safe"
BRANCH_COMMITS = [
    ("2017-10-14T22:40:00", MIRA, "wip: thread based watchdog",
     {"sundial/lock.py": LOCK_PY}),
    ("2017-11-19T15:12:00", MIRA, "wip: take a lock before every write",
     {"sundial/lock.py": LOCK_PY, "NOTES.md": None}),
    ("2017-12-02T20:33:00", MIRA, "wip: give up on threads, go back to fork",
     {"NOTES.md": None}),
]


# --------------------------------------------------------------------------
# Mechanics
# --------------------------------------------------------------------------


def run(args, env_extra=None, check=True):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": MIRA[0],
                "GIT_AUTHOR_EMAIL": MIRA[1], "GIT_COMMITTER_NAME": MIRA[0],
                "GIT_COMMITTER_EMAIL": MIRA[1]})
    if env_extra:
        env.update(env_extra)
    return subprocess.run(args, cwd=str(TARGET), env=env, check=check,
                          capture_output=True, text=True)


def write(path: str, text: str) -> None:
    dest = TARGET / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text if text.endswith("\n") else text + "\n")


class State:
    def __init__(self):
        self.grown: dict[str, int] = {}
        self.text: dict[str, str] = {}

    def grow(self, path: str, count: int) -> None:
        blocks = BLOCKS[path][:count]
        self.grown[path] = count
        self.text[path] = "\n".join(blocks)
        write(path, self.text[path])

    def edit(self, path: str, old: str, new: str) -> None:
        current = self.text.get(path) or (TARGET / path).read_text()
        if old not in current:
            raise SystemExit(f"edit failed: {old!r} not in {path}")
        self.text[path] = current.replace(old, new, 1)
        write(path, self.text[path])

    def version(self, value: str) -> None:
        write("setup.py", SETUP.format(version=value))
        write("sundial/__init__.py", INIT.format(version=value))


def commit(when, author, message, state, edits=None):
    name, email = author
    run(["git", "add", "-A"], env_extra={"GIT_AUTHOR_NAME": name,
                                         "GIT_AUTHOR_EMAIL": email})
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
           "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    run(["git", "commit", "-m", message, "--quiet", "--allow-empty"], env_extra=env)


def build(force: bool = False) -> Path:
    if TARGET.exists():
        if not force:
            print(f"{TARGET} already exists (use --force to rebuild)")
            return TARGET
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    run(["git", "init", "-q", "-b", "master"])
    run(["git", "config", "user.name", MIRA[0]])
    run(["git", "config", "user.email", MIRA[1]])
    run(["git", "config", "commit.gpgsign", "false"])

    state = State()
    write(".gitignore", GITIGNORE)
    write("LICENSE", LICENSE)
    state.version("0.1.0")

    shas: dict[str, str] = {}
    for when, author, message, grow, *rest in HISTORY:
        for path, count in grow.items():
            state.grow(path, count)
        for path, old, new in (rest[0] if rest else []):
            state.edit(path, old, new)
        if message.startswith("bump version to "):
            state.version(message.split("bump version to ", 1)[1])
        commit(when, author, message, state)
        shas[message] = run(["git", "rev-parse", "HEAD"]).stdout.strip()

    # Branch off where the 0.4 work started, and never merge it back.
    run(["git", "checkout", "-q", "-b", BRANCH,
         shas["start the 0.4 work: signal handling"]])

    branch_note = {
        1: "\n## 2017-11-19 — lock before write\n\nAdded `sundial/lock.py` on this branch. It deadlocks on the second start\nin the same terminal, so it stays here.\n",
        2: "\n## 2017-12-02 — gave up\n\nThreads cannot interrupt `time.sleep(30)` and the lock cannot survive\n`os._exit()`. Going back to the fork on master. Not deleting the branch, in\ncase I come back to it.\n",
    }
    for index, (when, author, message, grow) in enumerate(BRANCH_COMMITS):
        for path, content in grow.items():
            if path == "NOTES.md":
                notes = TARGET / "NOTES.md"
                notes.write_text(notes.read_text().rstrip() + "\n" + branch_note[index])
            else:
                write(path, content)
        commit(when, author, message, state)

    run(["git", "checkout", "-q", "master"])
    # leave the worktree exactly as master has it
    run(["git", "checkout", "-q", "--", "."])

    # A tag from before the silence.
    run(["git", "tag", "-a", "v0.3.2", "-m", "last tagged release",
         shas["0.3.2"]])

    print(f"built {TARGET}")
    print(run(["git", "log", "--oneline", "-5"]).stdout)
    print(run(["git", "log", "--oneline", f"master..{BRANCH}"]).stdout)
    return TARGET


if __name__ == "__main__":
    build(force="--force" in sys.argv)
