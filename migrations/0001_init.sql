-- עמותת שווים · קליטת מתמודד חדש · Cloudflare D1 schema
CREATE TABLE IF NOT EXISTS requests (
  id                  TEXT PRIMARY KEY,
  token               TEXT NOT NULL UNIQUE,          -- secret, in the referrer's personal link
  participant_name    TEXT NOT NULL,
  participant_id      TEXT NOT NULL,
  ref_name            TEXT NOT NULL,
  ref_email           TEXT NOT NULL,
  ref_phone           TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','submitted','approved')),
  possible_duplicate  INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  submitted_at        TEXT,
  approved_at         TEXT,
  thanks_sent_at      TEXT,
  last_reminder_at    TEXT,
  folder_name         TEXT,
  last_download_at    TEXT,
  fully_downloaded_at TEXT,
  purged_at           TEXT
);
CREATE INDEX IF NOT EXISTS requests_pid ON requests(participant_id);

CREATE TABLE IF NOT EXISTS files (
  id            TEXT PRIMARY KEY,
  request_id    TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  doc_type      TEXT NOT NULL CHECK (doc_type IN ('committee','psychiatric','social','medical','idcard')),
  original_name TEXT NOT NULL,
  kv_key        TEXT NOT NULL UNIQUE,
  size_bytes    INTEGER,
  mime          TEXT,
  uploaded_at   TEXT NOT NULL,
  downloaded_at TEXT
);
CREATE INDEX IF NOT EXISTS files_req ON files(request_id);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
  ip TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_ip ON login_attempts(ip, at);
