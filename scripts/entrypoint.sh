#!/bin/sh
set -e
python manage.py migrate --noinput
if [ "${SEED_DEMO:-1}" = "1" ]; then
  python manage.py seed_demo
fi
python manage.py collectstatic --noinput
exec gunicorn utilitypay.wsgi:application --bind 0.0.0.0:8000 --workers 2
