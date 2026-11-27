"""SQLite durable state (optimistic concurrency) and append-only, hash-chained event log."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import DrillError
from .security import canonical, mask

SCHEMA = """
CREATE TABLE IF NOT EXISTS drills(drill_id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, drill_id TEXT NOT NULL,
  body TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TABLE IF NOT EXISTS spans(id INTEGER PRIMARY KEY AUTOINCREMENT, drill_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS op_state(drill_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS op_ledger(idempotency_key TEXT PRIMARY KEY, drill_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS op_used_approvals(drill_id TEXT NOT NULL, approval_id TEXT NOT NULL,
  PRIMARY KEY(drill_id, approval_id));
"""
GENESIS = "0" * 64


def _chain(prev_hash, body):
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.executescript(SCHEMA)
        db.close()

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
        except BaseException:
            db.close()
            raise
        try:
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    # ---- drill state -------------------------------------------------------
    def get_drill_state(self, drill_id):
        with self.tx() as db:
            row = db.execute("SELECT version, state FROM drills WHERE drill_id=?", (drill_id,)).fetchone()
        if not row:
            raise DrillError("NOT_FOUND", "No drill with that id.")
        state = json.loads(row[1])
        state["state_version"] = row[0]
        return state

    def save_drill_state(self, drill_id, state, expected_version, events=()):
        """Write state and its events in one transaction. expected_version=0 creates the drill."""
        body = {k: v for k, v in state.items() if k != "state_version"}
        text = json.dumps(mask(body))
        with self.tx() as db:
            if expected_version == 0:
                db.execute("INSERT INTO drills VALUES(?,1,?)", (drill_id, text))
            else:
                done = db.execute("UPDATE drills SET version=version+1, state=? WHERE drill_id=? AND version=?",
                                  (text, drill_id, expected_version)).rowcount
                if not done:
                    raise DrillError("VERSION_CONFLICT", "The drill changed since you loaded it. Refresh and retry.")
            for event in events:
                self._append(db, drill_id, event)
        state["state_version"] = expected_version + 1
        return state["state_version"]

    def list_drills(self):
        with self.tx() as db:
            rows = db.execute("SELECT state FROM drills ORDER BY rowid DESC").fetchall()
        keys = ("drill_id", "application", "scenario_id", "status", "paused", "created_at")
        return [{k: json.loads(r[0])[k] for k in keys} for r in rows]

    # ---- events ------------------------------------------------------------
    def _append(self, db, drill_id, event):
        row = db.execute("SELECT hash FROM events WHERE drill_id=? ORDER BY seq DESC LIMIT 1", (drill_id,)).fetchone()
        prev = row[0] if row else GENESIS
        body = canonical(mask({**event, "drill_id": drill_id}))
        db.execute("INSERT INTO events(drill_id, body, prev_hash, hash) VALUES(?,?,?,?)",
                   (drill_id, body, prev, _chain(prev, body)))

    def log_event(self, drill_id, event):
        with self.tx() as db:
            self._append(db, drill_id, event)

    def get_events(self, drill_id, step_id=None, event_type=None, actor=None, status=None, since=None, until=None):
        with self.tx() as db:
            rows = db.execute("SELECT body, hash FROM events WHERE drill_id=? ORDER BY seq", (drill_id,)).fetchall()
        wanted = {"step_id": step_id, "event_type": event_type, "actor": actor, "status": status}
        out = []
        for body, event_hash in rows:
            event = json.loads(body)
            if any(v is not None and event.get(k) != v for k, v in wanted.items()):
                continue
            if (since and event["timestamp"] < since) or (until and event["timestamp"] > until):
                continue
            out.append({**event, "hash": event_hash})
        return out

    def verify_chain(self, drill_id):
        """Detects edited, removed or reordered events.

        ponytail: cutting off the newest events is only detectable against an outside copy of
        the head hash. The report prints it; ship it to write-once storage if that matters.
        """
        with self.tx() as db:
            rows = db.execute("SELECT body, prev_hash, hash FROM events WHERE drill_id=? ORDER BY seq",
                              (drill_id,)).fetchall()
        prev = GENESIS
        for body, prev_hash, event_hash in rows:
            if prev_hash != prev or _chain(prev, body) != event_hash:
                return False
            prev = event_hash
        return True

    # ---- trace spans -------------------------------------------------------
    def add_span(self, drill_id, span):
        with self.tx() as db:
            db.execute("INSERT INTO spans(drill_id, body) VALUES(?,?)", (drill_id, json.dumps(mask(span))))

    def get_spans(self, drill_id):
        with self.tx() as db:
            rows = db.execute("SELECT body FROM spans WHERE drill_id=? ORDER BY id", (drill_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]
