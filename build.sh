#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_temporadas   # temporadas.csv: grupos y partidas de cada temporada
python manage.py seed_partidas_manuales
python manage.py cargar_datos_avanzados
python manage.py cargar_datos_kblix --reset
python manage.py collectstatic --noinput