-- ═══════════════════════════════════════════
-- ReliefOps — SQLite Schema (Final)
-- ═══════════════════════════════════════════

PRAGMA foreign_keys = ON;

-- USERS
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK(role IN ('admin','donor','volunteer')),
    phone         TEXT,
    organization  TEXT,
    joined_date   TEXT    DEFAULT (date('now'))
);

-- DISASTERS
CREATE TABLE IF NOT EXISTS disaster (
    disaster_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    disaster_name  TEXT NOT NULL,
    disaster_type  TEXT NOT NULL,
    location       TEXT NOT NULL,
    severity_level TEXT NOT NULL CHECK(severity_level IN ('Low','Medium','High','Severe')),
    start_date     TEXT NOT NULL,
    end_date       TEXT,
    status         TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Closed','Monitoring')),
    lat            REAL,
    lng            REAL
);

-- RELIEF CAMPS
CREATE TABLE IF NOT EXISTS relief_camp (
    camp_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camp_name         TEXT    NOT NULL,
    location          TEXT    NOT NULL,
    total_capacity    INTEGER NOT NULL DEFAULT 0,
    current_occupancy INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Full','Closed')),
    opened_date       TEXT    DEFAULT NULL,
    disaster_id       INTEGER REFERENCES disaster(disaster_id) ON DELETE CASCADE
);

-- VOLUNTEER → CAMP assignment
CREATE TABLE IF NOT EXISTS volunteer_camp (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    camp_id     INTEGER NOT NULL REFERENCES relief_camp(camp_id) ON DELETE CASCADE,
    assigned_on TEXT    DEFAULT (date('now'))
);

-- RESOURCES
CREATE TABLE IF NOT EXISTS resource (
    resource_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_name      TEXT    NOT NULL,
    category           TEXT    NOT NULL,
    unit               TEXT    NOT NULL,
    quantity_available INTEGER NOT NULL DEFAULT 0,
    min_threshold      INTEGER NOT NULL DEFAULT 0
);

-- RESOURCE SHORTAGES (reported by volunteers)
CREATE TABLE IF NOT EXISTS resource_shortage (
    shortage_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    camp_id         INTEGER NOT NULL REFERENCES relief_camp(camp_id) ON DELETE CASCADE,
    resource_id     INTEGER NOT NULL REFERENCES resource(resource_id) ON DELETE CASCADE,
    reported_by     INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    quantity_needed INTEGER NOT NULL,
    remarks         TEXT,
    status          TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Allocated','Received')),
    reported_at     TEXT DEFAULT (datetime('now'))
);

-- RESOURCE ALLOCATIONS (admin dispatches to camp)
CREATE TABLE IF NOT EXISTS resource_allocation (
    allocation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id        INTEGER NOT NULL REFERENCES resource(resource_id) ON DELETE CASCADE,
    camp_id            INTEGER NOT NULL REFERENCES relief_camp(camp_id) ON DELETE CASCADE,
    shortage_id        INTEGER REFERENCES resource_shortage(shortage_id) ON DELETE SET NULL,
    quantity_dispatched INTEGER NOT NULL,
    allocation_date    TEXT    NOT NULL,
    allocated_by       INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    status             TEXT    NOT NULL DEFAULT 'Dispatched' CHECK(status IN ('Dispatched','Received'))
);

-- DONATIONS (donor → pending → admin accept/reject)
CREATE TABLE IF NOT EXISTS donation (
    donation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id      INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    resource_id   INTEGER NOT NULL REFERENCES resource(resource_id) ON DELETE CASCADE,
    quantity      INTEGER NOT NULL,
    donation_date TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Completed','Rejected')),
    remarks       TEXT,
    accepted_by   INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    accepted_at   TEXT
);

-- ACTIVITY LOG
CREATE TABLE IF NOT EXISTS activity_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT    NOT NULL,
    actor_name  TEXT    NOT NULL,
    actor_role  TEXT    NOT NULL,
    description TEXT    NOT NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    status      TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);