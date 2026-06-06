release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn ngoma_backend.wsgi --log-file -
