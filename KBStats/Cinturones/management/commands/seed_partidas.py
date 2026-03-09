import csv
import os
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import requests

from KBStats.Cinturones.models import Equipo, Partida
from KBStats.Cinturones.utils import extract_match_data, save_to_django


class Command(BaseCommand):
    help = 'Seed partidas desde el archivo seed_partidos.csv (crea Equipos si no existen)'

    def handle(self, *args, **options):
        file_path = Path(settings.BASE_DIR) / 'seed_partidos.csv'

        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"No se encontró {file_path}. Asegúrate de que el archivo exista."))
            return

        created = 0
        skipped = 0
        errors = 0

        api_key = os.environ.get('RIOT_API_KEY') or getattr(settings, 'RIOT_API_KEY', None)
        if not api_key:
            self.stdout.write(self.style.ERROR('No se encontró RIOT_API_KEY en variables de entorno o settings.'))
            self.stdout.write(self.style.ERROR('Exporta RIOT_API_KEY o añade RIOT_API_KEY en settings antes de ejecutar este comando.'))
            return

        with file_path.open(newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for nr, row in enumerate(reader, start=1):
                # Normalizar y saltar líneas vacías
                row = [c.strip() for c in row]
                if not any(row):
                    continue

                # Asegurar longitud mínima (pad with empty strings)
                while len(row) < 5:
                    row.append('')

                match_id, jornada, numero_partida, equipo_azul_name, equipo_rojo_name = row[:5]

                if not match_id:
                    self.stdout.write(self.style.WARNING(f"Línea {nr}: match_id vacío — se omite."))
                    skipped += 1
                    continue

                # Evitar duplicados
                if Partida.objects.filter(match_id=match_id).exists():
                    self.stdout.write(self.style.WARNING(f"Línea {nr}: Partida '{match_id}' ya existe — se omite."))
                    skipped += 1
                    continue

                # Equipo azul y rojo (validación mínima)
                if not equipo_azul_name or not equipo_rojo_name:
                    self.stdout.write(self.style.WARNING(f"Línea {nr}: falta nombre de equipo (azul/rojo) — se omite."))
                    skipped += 1
                    continue

                # Llamar a la API de Riot y usar las mismas utilidades que la vista add_partida
                api_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={api_key}"
                try:
                    resp = requests.get(api_url, timeout=30)
                    resp.raise_for_status()
                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"Línea {nr}: Error al obtener datos de la API para '{match_id}': {e}"))
                    # evitar peticiones excesivas en caso de fallos continuos
                    time.sleep(1)
                    continue

                # DEBUG: confirmar que vamos a llamar a extract_match_data
                try:
                    self.stdout.write(self.style.NOTICE(f"Línea {nr}: Llamando a extract_match_data para '{match_id}'"))
                except Exception:
                    pass

                # Intentar parsear/extraer datos de la respuesta
                try:
                    data = extract_match_data(resp.text, equipo_azul_name, equipo_rojo_name)
                except Exception as e:
                    data = {}
                    self.stdout.write(self.style.ERROR(f"Línea {nr}: Exception en extract_match_data para '{match_id}': {e}"))
                if not data:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"Línea {nr}: No se pudieron extraer datos para '{match_id}'. La función extract_match_data devolvió vacío."))
                    # Imprimir una porción de la respuesta para depuración
                    try:
                        preview = resp.text[:500]
                        self.stdout.write(self.style.WARNING(f"Línea {nr}: Respuesta (preview): {preview!r}"))
                    except Exception:
                        pass
                    time.sleep(0.5)
                    continue

                try:
                    # save_to_django ya maneja creación/actualización de Partida, Equipos y StatsJugador
                    save_to_django(data, jornada or None, numero_partida or None, equipo_azul_name, equipo_rojo_name)
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"Línea {nr}: Partida '{match_id}' importada y guardada."))
                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"Línea {nr}: Error guardando datos para '{match_id}': {e}"))
                # Pequeña pausa para evitar limites de la API
                time.sleep(0.5)

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(f"Seed partidas completado: {created} creadas, {skipped} omitidas, {errors} errores."))
