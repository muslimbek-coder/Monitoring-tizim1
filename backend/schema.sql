CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS school_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    viloyat TEXT NOT NULL,
    tuman TEXT NOT NULL,
    maktab TEXT NOT NULL,
    UNIQUE(viloyat, tuman, maktab)
);

CREATE TABLE IF NOT EXISTS responsible_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    school_location_id INTEGER NOT NULL
        REFERENCES school_locations(id) ON DELETE CASCADE,
    UNIQUE(username, school_location_id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sinf INTEGER NOT NULL,
    fish TEXT NOT NULL,
    school_location_id INTEGER REFERENCES school_locations(id),
    UNIQUE(sinf, fish, school_location_id)
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT,
    option_d TEXT,
    correct_option TEXT NOT NULL CHECK (correct_option IN ('a','b','c','d'))
);

-- Sinf (1-11) / Chorak (1-4) / Blok (1-3) bo'yicha 3 ta fan va sozlamalar
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sinf INTEGER NOT NULL,
    chorak INTEGER NOT NULL,
    blok INTEGER NOT NULL,
    subject1_id INTEGER REFERENCES subjects(id),
    subject2_id INTEGER REFERENCES subjects(id),
    subject3_id INTEGER REFERENCES subjects(id),
    entry_code TEXT,
    responsible_name TEXT,
    test_creator_name TEXT NOT NULL DEFAULT '',
    is_open INTEGER NOT NULL DEFAULT 0,
    UNIQUE(sinf, chorak, blok)
);

CREATE TABLE IF NOT EXISTS class_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_location_id INTEGER NOT NULL
        REFERENCES school_locations(id) ON DELETE CASCADE,
    sinf INTEGER NOT NULL,
    class_teacher_name TEXT NOT NULL,
    UNIQUE(school_location_id, sinf)
);

CREATE TABLE IF NOT EXISTS responsible_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    responsible_user_id INTEGER NOT NULL
        REFERENCES responsible_users(id) ON DELETE CASCADE,
    sinf INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    UNIQUE(responsible_user_id, sinf)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    block_id INTEGER NOT NULL REFERENCES blocks(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'started'  -- started / finished
);

CREATE TABLE IF NOT EXISTS session_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    position_in_subject INTEGER NOT NULL,  -- 1..15 shu fan ichida
    selected_option TEXT,
    is_correct INTEGER
);

CREATE TABLE IF NOT EXISTS telegram_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER UNIQUE NOT NULL,
    viloyat TEXT,
    tuman TEXT,
    maktab TEXT,
    student_id INTEGER REFERENCES students(id)
);
