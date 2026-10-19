-- Noa's check of each document type: 'ok' (תקין) or 'replace' (צריך להחליף).
-- Cleared automatically when the referrer uploads or removes a file of that type.
CREATE TABLE IF NOT EXISTS doc_reviews (
  request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  doc_type   TEXT NOT NULL CHECK (doc_type IN ('committee','psychiatric','social','medical','idcard')),
  state      TEXT NOT NULL CHECK (state IN ('ok','replace')),
  at         TEXT NOT NULL,
  PRIMARY KEY (request_id, doc_type)
);
