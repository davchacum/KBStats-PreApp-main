#!/usr/bin/env bash 
set -o errexit 
pip install -r requirements.txt 
python manage.py migrate 
python manage.py seed_grupos
python manage.py seed_users
python manage.py seed_partidas
python manage.py seed_partidas_manuales
python manage.py collectstatic --noinput