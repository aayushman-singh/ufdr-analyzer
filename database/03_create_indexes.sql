-- Full-Text Index for fast keyword searching on chat content (ILIKE/full-text search)
CREATE INDEX idx_messages_content ON Messages USING GIN (content);

-- Indexes for quick chronological and linking lookups
CREATE INDEX idx_calls_timestamp ON Calls (timestamp);
CREATE INDEX idx_messages_timestamp ON Messages (timestamp);
CREATE INDEX idx_calls_caller_receiver ON Calls (caller_id, receiver_id);