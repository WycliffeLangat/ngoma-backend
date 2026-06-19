release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn ngoma_backend.wsgi --log-file -
