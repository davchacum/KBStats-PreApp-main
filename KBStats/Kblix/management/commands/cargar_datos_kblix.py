from django.core.management.base import BaseCommand
from KBStats.Kblix.models import Jugador, Temporada, Equipo

DATOS = {
    'Split 2': {
        'Kaiju':       ['Dara', 'Cachimbas', 'Ulterior', 'Hyakko', 'Otarion', 'Tiger'],
        'Akarui':      ['Marakas', 'Cariatis', 'Mufasa', 'Gondal', 'Deiviaki'],
        'Kaizen':      ['ElCapitan', 'MnkyWlean', 'Reiko', 'Myrddin', 'Moon Magik'],
        'Bushi':       ['Chopito', 'Tusky', 'Vulpes', 'Leemon', 'Koku'],
        'Tora':        ['Patito', 'Mitsu', 'Freddy', 'Narciso', 'Zamore'],
        'Saru':        ['Juan Manuel', 'Sustanon', 'Alejandro', 'D4dtor', 'Rexito'],
        'Atsui':       ['Jarra', 'Dakin', 'Monchi', 'Karmac', 'Horizon'],
        'Ronin':       ['jk', 'Bakis', 'JoseOli', 'xRoxas', 'melon pan'],
        'Kuru':        ['Igrid', 'Sons', 'Hidon', 'Menos20', 'FrarX', 'Lolex', 'Reiko', 'Comunisma'],
        'Kemono':      ['TinkyWinky', 'Paellero', 'Ctrl4enjoyer', 'Dwailet', 'Isaacs'],
        'Toroi':       ['Edreira', 'Kutxi', 'Drago', 'Pais Vasco', 'Tominsa', 'Seda', 'Mith'],
        'Akuma':       ['Meleka', 'Humble', 'Krazel', 'Poro', 'Jordi'],
        'Kanji':       ['Angelgenius', 'JoseAngel', 'Ismael', 'Lythiumm', 'ZenithLeaf'],
        'Kenkujutsu':  ['Heart', 'overr', 'senpalvila', '88jefeantonio', 'Beta'],
    },
    'NBA Draft': {
        'Team Sons':   ['Nipa', 'Sune', 'Almope', 'Mari', 'Patito'],
        'Team Jarra':  ['Jarra', 'Dakin', 'Aolob', 'Delta', 'Zas'],
        'Team Deivi':  ['Espectro', 'Tusky', 'Marakas', 'Lirex', 'Deivi'],
        'Team Dwailet':['Kingkai', 'Mitsu', 'Dwailet', 'Narciso', 'Asessino'],
        'Team Reiko':  ['Miki', 'Echidna', 'Reiko', 'Lolex', 'Manue'],
        'Team Dato':   ['Kirby', 'Sustanon', 'Freddy', 'D4dtor', 'Sergi'],
    },
    'Open': {
        'Kaiju':     ['Myno', 'J Legend', 'Freddy', 'Davura', 'Sergi', 'Hyakko', 'Clavijo'],
        'Kb Amegos': ['Ragnarok', 'Lucas', 'Marakas', 'LegendLegacy', 'Ironfranman', 'Sergi'],
        'Saru':      ['Styler', 'Sustanon', 'Alejandro', 'D4dtor', 'Rexito', 'Xenius'],
        'Arashi':    ['Artorias', 'BuZz', 'AnPuuR', 'Lolex', 'Torrente'],
        'Atsui':     ['Gaatsu', 'Dakin', 'Sporfu', 'Dr Filtros', 'Coña mala', 'Lisbd','Invictutus'],
        'PSF':       ['Phantom', 'Mister G', 'Lucyfer', 'NdeNero', 'Alatriste'],
        'Kb CT':     ['Ann', 'Mitsu', 'Liss', 'Kenaka', 'Almope'],
    },
    'Sprint 4': {
        'Kaiju':     ['Despo', 'J Legend', 'Freddy', 'Davura', 'Sergi', 'Hyakko'],
        'Bushi':     ['Chopito', 'Tusky', 'Gallego', 'Leemon', 'Koku', 'Reiko', 'Ichigo'],
        'Saru':      ['Styler', 'Sustanon', 'Alejandro', 'D4dtor', 'Rexito', 'Kingkai', 'Nifi'],
        'Arashi':    ['Artorias', 'BuZz', 'AnPuuR', 'Cuco', 'Torrente', 'Deiviaki', 'Mecex'],
        'Tora':      ['Invictus', 'Xenius', 'AngelOwo', 'Narciso', 'Dantesaurio', 'Almope', 'Mitsu'],
        'Chiru':     ['Ragnarok', 'Thaiger', 'Qyrran', 'Gyokeres', 'Horizon', 'Karmac', 'Lucas', 'OuO', 'AgnesTachyon', 'LEA JUGKING'],
        'Atsui':     ['Gaatsu', 'Dakin', 'Sporfu', 'Dr Filtros', 'Coña mala', 'Komit', 'Dafenosa','Mitsu'],
        'Kamikaze':  ['Miki', 'Lolex', 'Ironfranman', 'Bastii','ILP'],
        'Kuru':      ['Comunisma', 'Hidon', 'Cariatis', 'LegendLegacy', 'Sons'],
        'PSF':       ['Phantom', 'Dayx', 'Lucyfer', 'NdeNero', 'Alatriste', 'Kingkai', 'Zroly', 'Jfet'],
        'Sorairo':   ['Farlopez', 'Polucion', 'Invictutus', 'Demon', 'Ranita', 'Marakas', 'Wesele', 'MaikyG', 'Duncan','DJMiniMatrix'],
        'Kanji':     ['Dara', 'Kaboshi', 'Makitah', 'Lythiumm', 'AngelGenius', 'xNeark', 'Diamond'],
        'Tabu':      ['Margakhan', 'Escuadra', 'Lady', 'Hazard', 'Arxan', 'Humble', 'Kuruta', 'Patoal', 'Fonkai', 'Huais'],
        'Kitsune':   ['HugoSexy', 'J4b4', 'Acelga', 'Bdd', 'Castañitas', 'Almope', 'Borjaocerin', 'Wiki', 'Potayu'],
        'Kb Madrid': ['Xenius', 'Reiko', 'Puncho', 'Coña mala', 'Despo'],
    },
    'Split 3': {
        'Kaiju':      ['Dara', 'Lucas', 'Liss', 'Hyakko', 'Kirito', 'Stryke'],
        'Bushi':      ['Chopito', 'Tusky', 'Leemon', 'Gallego', 'Koku', 'Ichigo', 'Vulpes'],
        'Saru':       ['Juan Manuel', 'Sustanon', 'Alejandro', 'D4dtor', 'Rexito', 'Arxan', 'James', 'McJuanjoDLC'],
        'Kemono':     ['Kingkai', 'Xenius', 'Dwailet', 'Davura', 'Sergi', 'Pamusa', 'Kokum'],
        'Tora':       ['Ann', 'Mitsu', 'Freddy', 'Narciso', 'Almope'],
        'Chiru':      ['Minito', 'Dakin', 'Sporfu', 'Karmac', 'Horizon', 'Xharon', 'Thaiger', 'Monchi'],
        'Saru 2':     ['Tusky', 'Sustanon', 'Alejandro', 'D4dtor', 'Rexito', 'Gaatsu', 'McJuanjoDLC'],
        'Kamikaze':   ['Miki', 'Tamayin', 'Reiko', 'Lolex', 'Ironfran', 'Echidna', 'Xenius', 'ElCapitan'],
        'Kuru':       ['Xhadow', 'Sons', 'Cariatis', 'Hidon', 'Patito'],
        'Doragon':    ['Pedro Angel', 'MaikyG', 'Kata', 'Demon', 'TTJow', 'Wesam'],
        'PSF':        ['Phantom', 'Kenaka', 'Lucyfer', 'NdeNero', 'Alatriste'],
        'Kanji':      ['Deiviaki', 'Padeco', 'Honda', 'Lythiumm', 'Ismael', 'Stryke', 'menos20'],
        'Kanji 2':    ['The White Shark', 'Mr Martinez', 'Carlitos', 'Lythiumm', 'Deiviaki', 'ElSobrao', 'Stryke'],
        'Atsui':      ['Jarra', 'Dakin', 'Ventana', 'Dafenosa', 'Adrimerk'],
        'Tora 2':     ['Ann', 'Mitsu', 'Zoe', 'Narciso', 'Almope'],
        'Amateratsu': ['TinkyWinky', 'ILP', 'SPJaina', 'Nihility', 'Coña mala'],
        'KamiSaru':   ['Lolex', 'Sustanon', 'Reiko', 'Ironfranman', 'Rexito', 'Miki', 'Hazard'],
        'Tora 3':     ['Ann', 'Mitsu', 'Freddy', 'D4dtor', 'Almope'],
    },
}


class Command(BaseCommand):
    help = 'Carga los jugadores y equipos de KBLIX. Usa --reset para borrar todo primero.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra todos los datos antes de cargar')

    def handle(self, *args, **kwargs):
        if kwargs['reset']:
            Equipo.objects.all().delete()
            Jugador.objects.all().delete()
            Temporada.objects.all().delete()
            self.stdout.write(self.style.WARNING('Datos KBLIX borrados.'))

        total_jugadores = 0
        total_equipos = 0

        for temporada_nombre, equipos in DATOS.items():
            temporada, _ = Temporada.objects.get_or_create(nombre=temporada_nombre)
            self.stdout.write(f'\nTemporada: {temporada_nombre}')

            for equipo_nombre, jugadores in equipos.items():
                equipo, created = Equipo.objects.get_or_create(
                    nombre=equipo_nombre,
                    temporada=temporada,
                )
                if created:
                    total_equipos += 1

                for nombre in jugadores:
                    jugador, _ = Jugador.objects.get_or_create(nombre=nombre)
                    equipo.jugadores.add(jugador)
                    total_jugadores += 1

                self.stdout.write(f'  {equipo_nombre}: {len(jugadores)} jugadores')

        self.stdout.write(self.style.SUCCESS(
            f'\nListo. {total_equipos} equipos y {total_jugadores} asignaciones cargadas.'
        ))
