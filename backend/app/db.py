"""Thread-safe SQLite storage for cached measurements, history and scans."""
import json
import sqlite3
import threading
from pathlib import Path


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS raw_cache (full_name TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, raw TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, ts TEXT NOT NULL, score REAL, risk TEXT, categories TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS history_name_ts ON history(full_name, ts);
                CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, created TEXT NOT NULL, status TEXT NOT NULL, total INTEGER NOT NULL, done INTEGER NOT NULL, payload TEXT NOT NULL);
            """)
            self.connection.commit()

    def get_cache(self, full_name: str):
        with self.lock:
            row = self.connection.execute("SELECT fetched_at, raw FROM raw_cache WHERE full_name = ?", (full_name.lower(),)).fetchone()
        return {"fetched_at": row["fetched_at"], "raw": json.loads(row["raw"])} if row else None

    def put_cache(self, full_name: str, fetched_at: str, raw: dict):
        with self.lock:
            self.connection.execute("INSERT OR REPLACE INTO raw_cache VALUES (?, ?, ?)", (full_name.lower(), fetched_at, json.dumps(raw)))
            self.connection.commit()

    def add_history(self, full_name: str, ts: str, score, risk, categories: dict):
        with self.lock:
            self.connection.execute("INSERT INTO history (full_name, ts, score, risk, categories) VALUES (?, ?, ?, ?, ?)", (full_name.lower(), ts, score, risk, json.dumps(categories)))
            self.connection.commit()

    def get_history(self, full_name: str):
        with self.lock:
            rows = self.connection.execute("SELECT ts, score, risk, categories FROM history WHERE full_name = ? ORDER BY ts, id", (full_name.lower(),)).fetchall()
        return [{**dict(row), "categories": json.loads(row["categories"])} for row in rows]

    def save_scan(self, job_id: str, created: str, status: str, total: int, done: int, payload: dict):
        with self.lock:
            self.connection.execute("INSERT OR REPLACE INTO scans VALUES (?, ?, ?, ?, ?, ?)", (job_id, created, status, total, done, json.dumps(payload)))
            self.connection.commit()

    def get_scan(self, job_id: str):
        with self.lock:
            row = self.connection.execute("SELECT * FROM scans WHERE id = ?", (job_id,)).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def close(self):
        with self.lock:
            self.connection.close()
