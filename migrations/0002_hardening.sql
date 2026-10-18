-- Rate limiting for new requests, Noa's archive, index for the daily cleanup
CREATE TABLE IF NOT EXISTS events (
  kind TEXT NOT NULL,      -- 'create'
  ip   TEXT NOT NULL,
  at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind_ip ON events(kind, ip, at);

ALTER TABLE requests ADD COLUMN archived_at TEXT;   -- Noa moved it out of the main list (details kept)

CREATE INDEX IF NOT EXISTS requests_cleanup ON requests(status, purged_at, fully_downloaded_at);
CREATE INDEX IF NOT EXISTS login_attempts_at ON login_attempts(at);
