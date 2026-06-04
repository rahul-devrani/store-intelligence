import sqlite3
import os



def get_db_path():
    return os.environ.get(
        "DB_PATH",
        "/app/data/store_intelligence.db"
    )


def init_db():
    # os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # conn = sqlite3.connect(DB_PATH)

    db_path = get_db_path()

    os.makedirs(
    os.path.dirname(db_path),
    exist_ok=True
        )

    # conn = sqlite3.connect(db_path)
    # conn = sqlite3.connect(get_db_path())
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            visitor_id   TEXT NOT NULL,
            store_id     TEXT NOT NULL,
            is_staff     INTEGER DEFAULT 0,
            PRIMARY KEY (visitor_id, store_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitor_sessions (
            session_id            TEXT PRIMARY KEY,
            store_id              TEXT NOT NULL,
            visitor_id            TEXT NOT NULL,
            start_time            REAL NOT NULL,
            end_time              REAL,
            is_staff              INTEGER DEFAULT 0,
            unauthorized_backroom INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS raw_events (
            event_id    TEXT PRIMARY KEY,
            store_id    TEXT NOT NULL,
            camera_id   TEXT NOT NULL,
            visitor_id  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            timestamp   REAL NOT NULL,
            zone_id     TEXT,
            dwell_ms    INTEGER DEFAULT 0,
            is_staff    INTEGER DEFAULT 0,
            queue_depth INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS heatmap_bins (
            store_id        TEXT    NOT NULL,
            x_grid          INTEGER NOT NULL,
            y_grid          INTEGER NOT NULL,
            frequency_count INTEGER DEFAULT 0,
            PRIMARY KEY (store_id, x_grid, y_grid)
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_store_ts  ON raw_events(store_id, timestamp);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_visitor   ON raw_events(store_id, visitor_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_visitor ON visitor_sessions(store_id, visitor_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_visitors_store   ON visitors(store_id);")

    conn.commit()
    conn.close()


# def get_db_connection() -> sqlite3.Connection:
#     conn = sqlite3.connect(DB_PATH)
#     conn.row_factory = sqlite3.Row
#     return conn

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn