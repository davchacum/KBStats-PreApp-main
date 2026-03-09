from django.core.management.base import BaseCommand
from KBStats.Cinturones.models import Equipo
import csv
from pathlib import Path


class Command(BaseCommand):
    help = 'Seed equipos desde seed_grupos.csv'

    def handle(self, *args, **options):
        # Ruta al archivo CSV en la raíz del proyecto
        base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
        csv_path = base_dir / 'seed_grupos.csv'

        if not csv_path.exists():
            self.stdout.write(self.style.ERROR(f"Archivo {csv_path} no encontrado."))
            return

        equipos_creados = 0
        equipos_existentes = 0

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                # row[0] es el nombre del grupo (SOMBRA, SOL, etc.)
                # row[1:] son los equipos de ese grupo
                grupo_nombre = row[0]
                equipos = row[1:]
                
                for equipo_nombre in equipos:
                    equipo_nombre = equipo_nombre.strip()
                    if not equipo_nombre:
                        continue
                    
                    if Equipo.objects.filter(nombre=equipo_nombre).exists():
                        self.stdout.write(self.style.WARNING(f"Equipo '{equipo_nombre}' ya existe. Omitiendo."))
                        equipos_existentes += 1
                    else:
                        Equipo.objects.create(nombre=equipo_nombre)
                        self.stdout.write(self.style.SUCCESS(f"Equipo '{equipo_nombre}' creado (Grupo: {grupo_nombre})."))
                        equipos_creados += 1

        self.stdout.write(self.style.NOTICE(
            f'Seed de grupos completado. Creados: {equipos_creados}, Ya existentes: {equipos_existentes}'
        ))
