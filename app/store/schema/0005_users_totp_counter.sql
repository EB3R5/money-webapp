-- TOTP replay guard: the time-step counter of the last accepted code (login hardening).
ALTER TABLE users ADD COLUMN last_totp_counter INTEGER;
