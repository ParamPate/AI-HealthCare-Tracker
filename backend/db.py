import sqlite3, json
from pathlib import Path

DB_PATH = Path(__file__).parent / "healthcare.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seat_id TEXT NOT NULL,
        name TEXT NOT NULL,
        age INTEGER,
        sex TEXT,
        chief_complaint TEXT,
        symptoms TEXT DEFAULT '{}',
        baseline_hr REAL,
        baseline_resp_amp REAL,
        checkin_time TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS vitals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seat_id TEXT NOT NULL,
        ts TEXT DEFAULT CURRENT_TIMESTAMP,
        hr REAL, rr REAL, confidence REAL,
        breathing_pattern TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_vitals_seat_ts ON vitals(seat_id, ts);
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seat_id TEXT NOT NULL,
        ts TEXT DEFAULT CURRENT_TIMESTAMP,
        hr REAL, rr REAL,
        severity TEXT,
        breathing_pattern TEXT,
        acknowledged INTEGER DEFAULT 0,
        waveform_snapshot TEXT
    );
    CREATE TABLE IF NOT EXISTS triage_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id INTEGER REFERENCES alerts(id),
        differential TEXT,
        ctas_level INTEGER,
        recommended_actions TEXT,
        reasoning TEXT,
        ts TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()
