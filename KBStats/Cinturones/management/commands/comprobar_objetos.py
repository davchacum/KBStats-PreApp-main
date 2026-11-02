"""
Busca objetos usados en las partidas que no tienen icono en la versión de Data Dragon configurada
(DDRAGON_VERSION) porque Riot los ha quitado del juego, y dice la última versión en la que existen.

    python manage.py comprobar_objetos

Conviene ejecutarlo al subir DDRAGON_VERSION. Las líneas que imprime van en OBJETOS_RETIRADOS (ddragon.py).
"""
import json
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from KBStats.Cinturones.ddragon import OBJETOS_RETIRADOS
from KBStats.Cinturones.models import StatsJugador

DDRAGON = 'https://ddragon.leagueoflegends.com'


def _json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def _objetos(version):
    return _json(f'{DDRAGON}/cdn/{version}/data/es_ES/item.json')['data']


class Command(BaseCommand):
    help = 'Busca objetos retirados del juego que no tienen icono en la versión de Data Dragon configurada'

    def add_arguments(self, parser):
        parser.add_argument('--max-versiones', type=int, default=60,
                            help='Cuántas versiones anteriores revisar como mucho (por defecto 60)')

    def handle(self, *args, **options):
        usados = set()
        for extra in StatsJugador.objects.values_list('riot_extra', flat=True):
            usados.update(i for i in (extra or {}).get('objetos') or [] if i)

        actuales = _objetos(settings.DDRAGON_VERSION)
        faltan = sorted(i for i in usados if str(i) not in actuales and i not in OBJETOS_RETIRADOS)
        self.stdout.write(f'{len(usados)} objetos usados en la liga; versión configurada {settings.DDRAGON_VERSION}.')
        if not faltan:
            self.stdout.write(self.style.SUCCESS('Todos tienen icono.'))
            return
        self.stdout.write(f'Sin icono: {", ".join(map(str, faltan))}. Buscando en versiones anteriores...')

        versiones = _json(f'{DDRAGON}/api/versions.json')
        if settings.DDRAGON_VERSION in versiones:
            versiones = versiones[versiones.index(settings.DDRAGON_VERSION) + 1:]
        encontrados = {}
        for version in versiones[:options['max_versiones']]:
            datos = _objetos(version)
            for i in faltan:
                if i not in encontrados and str(i) in datos:
                    encontrados[i] = (version, datos[str(i)]['name'])
            if len(encontrados) == len(faltan):
                break

        if encontrados:
            self.stdout.write('\nAñade a OBJETOS_RETIRADOS en KBStats/Cinturones/ddragon.py:')
            for i, (version, nombre) in sorted(encontrados.items()):
                self.stdout.write(f"    {i}: ('{version}', '{nombre}'),")
        sin_encontrar = [i for i in faltan if i not in encontrados]
        if sin_encontrar:
            self.stdout.write(self.style.WARNING(
                f'\nNo encontrados en las últimas {options["max_versiones"]} versiones: {", ".join(map(str, sin_encontrar))} '
                '(se verá el hueco vacío).'))
