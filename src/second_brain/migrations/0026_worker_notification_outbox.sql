-- Post-commit notification outbox for worker terminal events.
--
-- The terminal fact and the intent to notify commit in the same transaction, so a crash or
-- failure in the emit window leaves a durable, reconstructible intent instead of a lost
-- event -- and never turns a committed recording into a reported failure. Delivery status is
-- tracked separately from recording status; the derived event id is content-addressed, so a
-- repeated delivery cannot record the event twice.
ALTER TABLE worker_task_meta ADD COLUMN notification_event_key TEXT;
ALTER TABLE worker_task_meta ADD COLUMN notification_pending INTEGER NOT NULL DEFAULT 0;
ALTER TABLE worker_task_meta ADD COLUMN notification_delivered_at TEXT;
