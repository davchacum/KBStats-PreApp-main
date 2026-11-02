"""
Crea las temporadas de temporadas.csv y carga sus grupos y sus partidas.

    python manage.py seed_temporadas

Para añadir una temporada: sus CSV en la raíz (partidas y, si tiene, grupos) y una línea en temporadas.csv.
Si aún no existe el archivo de partidas de una temporada, se crea vacía y no sale en la web hasta que tenga partidas.
"""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from KBStats.Cinturones.models import Equipo, Partida, Temporada
from KBStats.Cinturones.temporadas import leer_config, leer_grupos


class Command(BaseCommand):
    help = 'Crea las temporadas de temporadas.csv y carga sus grupos y partidas'

    def handle(self, *args, **options):
        config = leer_config()
        if not config:
            self.stdout.write(self.style.ERROR('No hay temporadas en temporadas.csv.'))
            return

        for orden, t in enumerate(config, start=1):
            grupos = leer_grupos(t['grupos'])
            temporada, creada = Temporada.objects.update_or_create(
                slug=t['slug'], defaults={'nombre': t['nombre'], 'orden': orden, 'grupos': grupos})
            for g in grupos:
                for nombre in g['equipos']:
                    Equipo.objects.get_or_create(nombre=nombre)
            self.stdout.write(self.style.NOTICE(
                f"{temporada.nombre}{' (nueva)' if creada else ''}: {len(grupos)} grupo{'s' if len(grupos) != 1 else ''}"))

            if t['partidas'] and (settings.BASE_DIR / t['partidas']).exists():
                call_command('seed_partidas', file=t['partidas'], temporada=t['slug'], stdout=self.stdout)
            else:
                self.stdout.write(f"  Sin archivo de partidas ({t['partidas'] or '—'}) todavía.")

        sueltas = Partida.objects.filter(temporada__isnull=True).count()
        if sueltas:
            self.stdout.write(self.style.WARNING(
                f'{sueltas} partidas no están en ningún archivo de temporada y no saldrán en la web.'))
