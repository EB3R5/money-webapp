#!/bin/sh
# Every start: the store's schema files, Django's migrations, then the first account when
# DEFAULT_USER / DEFAULT_PASSWORD are set (otherwise /login offers the setup form).
# The jobs container runs the same image with `python manage.py run_jobs` and starts after
# the web one is healthy (compose depends_on), so only one process applies the schema.
set -e
cd /app
python manage.py init_store
python manage.py migrate --noinput -v 0
python manage.py bootstrap_admin
exec "$@"
