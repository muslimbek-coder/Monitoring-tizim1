"""
SQLite ulanishi. Web-ilova (FastAPI) va Telegram bot BIR XIL monitoring.db
faylidan foydalanadi — shuning uchun natijalar ikkala tomonda ham bir xil
ko'rinadi.
"""
import sqlite3
from pathlib import Path

from .signers import SIGNER_ROLES

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "monitoring.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.executemany(
            "INSERT OR IGNORE INTO monitoring_signers (role) VALUES (?)",
            [(role,) for role, _ in SIGNER_ROLES],
        )
        conn.commit()

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(students)").fetchall()
        }
        has_old_unique = False
        for index in conn.execute("PRAGMA index_list(students)").fetchall():
            if not index["unique"]:
                continue
            quoted_name = index["name"].replace('"', '""')
            indexed_columns = [
                row["name"]
                for row in conn.execute(
                    f'PRAGMA index_info("{quoted_name}")'
                ).fetchall()
            ]
            if indexed_columns == ["sinf", "fish"]:
                has_old_unique = True
                break

        if "school_location_id" not in columns or has_old_unique:
            location_column = (
                "school_location_id"
                if "school_location_id" in columns
                else "NULL"
            )
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    CREATE TABLE students_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sinf INTEGER NOT NULL,
                        fish TEXT NOT NULL,
                        school_location_id INTEGER
                            REFERENCES school_locations(id),
                        UNIQUE(sinf, fish, school_location_id)
                    )
                    """
                )
                conn.execute(
                    f"""
                    INSERT INTO students_new
                        (id, sinf, fish, school_location_id)
                    SELECT id, sinf, fish, {location_column}
                    FROM students
                    """
                )
                conn.execute("DROP TABLE students")
                conn.execute(
                    "ALTER TABLE students_new RENAME TO students"
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

        block_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(blocks)").fetchall()
        }
        if "test_creator_name" not in block_columns:
            conn.execute(
                """
                ALTER TABLE blocks
                ADD COLUMN test_creator_name TEXT NOT NULL DEFAULT ''
                """
            )
            conn.commit()
    finally:
        conn.close()
