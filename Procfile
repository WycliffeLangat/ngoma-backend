release: python manage.py migrate --noinput && python manage.py collectstatic --noinput && python manage.py merge_duplicate_releases --file "Data/ngoma_duplicate_releases_final_merge_ready.xlsx" && python manage.py clean_artist_aliases && python manage.py purge_release_duplicates
web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && (python manage.py process_chart_jobs --sleep 2 &) && gunicorn ngoma_backend.wsgi --workers 2 --timeout 900 --log-file -
worker: python manage.py process_chart_jobs --sleep 2
