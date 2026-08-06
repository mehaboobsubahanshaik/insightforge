# ADR 0010 - File outbox mailer in dev, SMTP in prod

**Status**: accepted

All email renders to .eml files in an outbox volume unless SMTP_HOST is set - deterministic tests, inspectable dev, zero accidental sends.
