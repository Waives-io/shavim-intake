-- Noa's own password, set from inside the dashboard ("שינוי סיסמה").
-- While this row does not exist, the STAFF_PASSWORD secret is used.
CREATE TABLE IF NOT EXISTS staff_auth (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  salt       TEXT NOT NULL,
  hash       TEXT NOT NULL,     -- PBKDF2-SHA256
  updated_at TEXT NOT NULL
);
