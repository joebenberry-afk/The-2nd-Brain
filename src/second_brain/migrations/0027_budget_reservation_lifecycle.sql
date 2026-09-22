-- Reservation lifecycle: only proven-unused capacity may be returned; uncertainty stays a
-- liability. cancelled_at marks a refund (excluded from outstanding), resolved_at records the
-- terminal decision, and unresolved reservations keep their accounting until evidence arrives.
ALTER TABLE budget_reservations ADD COLUMN episode_id TEXT;
ALTER TABLE budget_reservations ADD COLUMN cancelled_at TEXT;
ALTER TABLE budget_reservations ADD COLUMN cancel_reason TEXT;
ALTER TABLE budget_reservations ADD COLUMN resolved_at TEXT;
ALTER TABLE budget_reservations ADD COLUMN resolution TEXT;
ALTER TABLE budget_reservations ADD COLUMN actual_tokens INTEGER;
