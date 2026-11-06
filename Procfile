web: gunicorn biospine_project.wsgi:application --workers 2 --timeout 60 --log-file -
release: python manage.py migrate --noinput
