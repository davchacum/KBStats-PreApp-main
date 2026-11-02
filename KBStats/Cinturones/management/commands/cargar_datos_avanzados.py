"""
Rellena `StatsJugador.riot_extra` (campos avanzados de Riot que usa la nota de rendimiento)
para las partidas ya importadas: los del bloque `challenges` (match-v5), y del timeline las placas
de torre y el oro, la experiencia y el CS de cada jugador minuto a minuto (gráfica de oro).
Solo pide a la API lo que falta.

Uso:
    python manage.py cargar_datos_avanzados            # solo las que faltan
    python manage.py cargar_datos_avanzados --forzar   # todas
"""
import os
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from KBStats.Cinturones.models import Partida
from KBStats.Cinturones.utils import extraer_riot_extra, placas_por_participante, curvas_por_participante, _apply_name_alias

API = 'https://europe.api.riotgames.com/lol/match/v5/matches/'


class Command(BaseCommand):
    help = 'Descarga de Riot los datos avanzados (challenges y placas) de las partidas que no los tienen'

    def add_arguments(self, parser):
        parser.add_argument('--forzar', action='store_true', help='Vuelve a descargar también las que ya los tienen')

    def handle(self, *args, **options):
        api_key = os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)
        if not api_key:
            self.stdout.write(self.style.WARNING('Sin RIOT_API_KEY: no se cargan datos avanzados.'))
            return

        hechas = saltadas = errores = 0
        for partida in Partida.objects.order_by('id'):
            stats = list(partida.stats_jugadores.select_related('jugador'))
            if not stats:
                continue
            completa = all(s.riot_extra and all(k in s.riot_extra for k in ('placas', 'objetos', 'oro_t')) for s in stats)
            if completa and not options['forzar']:
                saltadas += 1
                continue

            datos = self._pedir(API + partida.match_id, api_key)
            timeline = self._pedir(API + partida.match_id + '/timeline', api_key)
            if datos is None or timeline is None:
                errores += 1  # sin los dos no se toca nada (no se pierden las placas ni el oro ya guardados)
                continue
            placas = placas_por_participante(timeline)
            curvas = curvas_por_participante(timeline)

            participantes = datos.get('info', {}).get('participants', [])
            por_campeon = {p.get('championName'): p for p in participantes}
            por_nombre = {
                _apply_name_alias(f"{p.get('riotIdGameName', '')}#{p.get('riotIdTagline', '')}").lower(): p
                for p in participantes
            }

            actualizados = 0
            for s in stats:
                # Cada campeón es único en una partida: es la forma más fiable de emparejar
                p = por_campeon.get(s.campeon) or por_nombre.get(s.jugador.nombre.lower())
                if not p:
                    continue
                extra = extraer_riot_extra(p)
                if placas is not None:
                    extra['placas'] = placas.get(p.get('participantId'), 0)
                extra.update(curvas.get(p.get('participantId'), {}))
                s.riot_extra = extra
                s.save(update_fields=['riot_extra'])
                actualizados += 1

            hechas += 1
            self.stdout.write(f'{partida.match_id}: {actualizados}/{len(stats)} jugadores')
            time.sleep(2.5)  # dos peticiones por partida; límite de la clave de desarrollo: 100 cada 2 min

        self.stdout.write(self.style.SUCCESS(
            f'Datos avanzados: {hechas} partidas actualizadas, {saltadas} ya estaban, {errores} errores.'
        ))

    def _pedir(self, url, api_key):
        for _ in range(4):
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
                return r.json()
            self.stdout.write(self.style.ERROR(f'{url.rsplit("/", 2)[-2:]}: respuesta {r.status_code}'))
            return None
        return None
