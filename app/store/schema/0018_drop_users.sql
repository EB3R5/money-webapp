-- The legacy login credential (ADR-0024's cutover): the one `users` row was imported into
-- django.contrib.auth at the first start of the Django build, so the table goes. Its
-- password hash lives on as the Django user's; nothing else referenced it.
DROP TABLE IF EXISTS users;
