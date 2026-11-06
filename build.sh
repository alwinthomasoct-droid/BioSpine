#!/usr/bin/env bash
# Build step used by Render (or any host): install, collect static files, migrate the database.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
