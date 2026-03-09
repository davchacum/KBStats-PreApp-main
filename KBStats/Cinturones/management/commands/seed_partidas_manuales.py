from django.core.management.base import BaseCommand

from KBStats.Cinturones.utils import save_to_django


class Command(BaseCommand):
	help = 'Insertar manualmente una partida específica (Partido 6: KB KB BUSHI vs KB KB KAIJU)'

	def handle(self, *args, **options):
		skipped = 0
