-- A file the referrer replaced after Noa marked "צריך להחליף": kept for history, no longer counted.
ALTER TABLE files ADD COLUMN replaced_at TEXT;

-- New review state 'check' (לבדיקה): a new file arrived for a document Noa had already reviewed.
CREATE TABLE doc_reviews_new (
  request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  doc_type   TEXT NOT NULL CHECK (doc_type IN ('committee','psychiatric','social','medical','idcard')),
  state      TEXT NOT NULL CHECK (state IN ('ok','replace','check')),
  at         TEXT NOT NULL,
  PRIMARY KEY (request_id, doc_type)
);
INSERT INTO doc_reviews_new (request_id, doc_type, state, at) SELECT request_id, doc_type, state, at FROM doc_reviews;
DROP TABLE doc_reviews;
ALTER TABLE doc_reviews_new RENAME TO doc_reviews;
