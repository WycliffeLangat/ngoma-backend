release: python manage.py migrate --noinput && python manage.py collectstatic --noinput && python manage.py merge_duplicate_releases --file "Data/ngoma_duplicate_releases_final_merge_ready.xlsx"
web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn ngoma_backend.wsgi --log-file -
