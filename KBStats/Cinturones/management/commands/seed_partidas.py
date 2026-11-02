"""
Importa partidas de Riot desde un CSV: match_id,jornada,game,equipo azul,equipo rojo

    python manage.py seed_partidas --file seed_partidos.csv --temporada t4

Normalmente no se usa a mano: `seed_temporadas` lo llama con el archivo de cada temporada.
Las partidas que ya están no se vuelven a pedir (solo se les pone la temporada si les falta).
Si un match_id sale repetido en el archivo con datos distintos, se queda la versión que más se repite.
"""
import os
import time
from collections import Counter
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

import requests

from KBStats.Cinturones.models import Partida, Temporada
from KBStats.Cinturones.utils import extract_match_data, save_to_django, extract_positions_from_timeline, update_early_game_stats

API = 'https://europe.api.riotgames.com/lol/match/v5/matches/'


class Command(BaseCommand):
    help = 'Importa partidas desde un archivo CSV (crea los equipos si no existen)'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, default='seed_partidos.csv',
                            help='Archivo CSV en la raíz del proyecto (por defecto: seed_partidos.csv)')
        parser.add_argument('--temporada', type=str, default=None,
                            help='Slug de la temporada a la que pertenecen (ver temporadas.csv)')

    def handle(self, *args, **options):
        file_path = Path(settings.BASE_DIR) / options['file']
        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"No se encontró {file_path}."))
            return

        temporada = None
        if options['temporada']:
            temporada = Temporada.objects.filter(slug=options['temporada']).first()
            if not temporada:
                self.stdout.write(self.style.ERROR(f"No existe la temporada '{options['temporada']}'. Ejecuta seed_temporadas."))
                return

        filas = self._leer(file_path)
        nuevas = [f for f in filas if not Partida.objects.filter(match_id=f[0]).exists()]

        # Las que ya están: solo se les pone la temporada
        if temporada:
            ya = Partida.objects.filter(match_id__in=[f[0] for f in filas]).exclude(temporada=temporada)
            n = ya.update(temporada=temporada)
            if n:
                self.stdout.write(f'{n} partidas ya importadas asignadas a {temporada.nombre}.')

        if not nuevas:
            self.stdout.write(self.style.NOTICE(f'{options["file"]}: {len(filas)} partidas, ninguna nueva.'))
            return

        api_key = os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)
        if not api_key:
            self.stdout.write(self.style.ERROR(f'Sin RIOT_API_KEY: no se pueden importar las {len(nuevas)} partidas nuevas.'))
            return

        creadas = errores = 0
        for match_id, jornada, numero, azul, rojo in nuevas:
            resp = self._pedir(API + match_id, api_key)
            if resp is None:
                errores += 1
                continue
            try:
                data = extract_match_data(resp.text, azul, rojo)
            except Exception as e:
                data = {}
                self.stdout.write(self.style.ERROR(f"{match_id}: error leyendo la partida: {e}"))
            if not data:
                errores += 1
                continue
            try:
                save_to_django(data, jornada or None, numero or None, azul, rojo, temporada=temporada)
                creadas += 1
                self.stdout.write(self.style.SUCCESS(f"{match_id}: importada ({jornada} · {azul} vs {rojo})."))
            except Exception as e:
                errores += 1
                self.stdout.write(self.style.ERROR(f"{match_id}: error guardando: {e}"))
                continue

            # Timeline: posiciones para el mapa de calor y estadísticas de early game
            t_resp = self._pedir(API + match_id + '/timeline', api_key)
            if t_resp is not None:
                try:
                    pos = extract_positions_from_timeline(t_resp.text, resp.text)
                    if pos:
                        Partida.objects.filter(match_id=match_id).update(position_data=pos)
                    update_early_game_stats(t_resp.text, resp.text, match_id)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"{match_id}: sin posiciones/early game: {e}"))
            time.sleep(1.2)   # dos peticiones por partida; límite de la clave de desarrollo: 100 cada 2 min

        self.stdout.write(self.style.NOTICE(f'{options["file"]}: {creadas} importadas, {errores} errores, {len(filas) - len(nuevas)} ya estaban.'))

    def _leer(self, file_path):
        """Filas únicas por match_id. Si una partida sale varias veces con datos distintos, gana la más repetida."""
        por_id = {}
        with file_path.open(newline='', encoding='utf-8') as f:
            for row in csv.reader(f):
                row = [c.strip() for c in row]
                if not row or not row[0] or row[0].startswith('#'):
                    continue
                row += [''] * (5 - len(row))
                if not row[3] or not row[4]:
                    self.stdout.write(self.style.WARNING(f"{row[0]}: falta algún equipo, se omite."))
                    continue
                por_id.setdefault(row[0], Counter())[tuple(row[1:5])] += 1
        filas = []
        for match_id, versiones in por_id.items():
            elegida = versiones.most_common(1)[0][0]
            if len(versiones) > 1:
                otras = '; '.join(' · '.join(v) for v in versiones if v != elegida)
                self.stdout.write(self.style.WARNING(
                    f"{match_id} sale con datos distintos. Se usa «{' · '.join(elegida)}» (descartado: {otras})."))
            filas.append((match_id, *elegida))
        return filas

    def _pedir(self, url, api_key):
        for _ in range(5):
            try:
                r = requests.get(url, headers={'X-Riot-Token': api_key}, timeout=30)
            except requests.RequestException as e:
                self.stdout.write(self.style.WARNING(f'Error de red ({e}), reintento'))
                time.sleep(3)
                continue
            if r.status_code == 429:
                espera = int(r.headers.get('Retry-After', '10'))
                self.stdout.write(f'Límite de la API, espero {espera} s')
                time.sleep(espera)
                continue
            if r.ok:
                return r
            self.stdout.write(self.style.ERROR(f'{url.rsplit("/", 2)[-2:]}: respuesta {r.status_code}'))
            return None
        return None
