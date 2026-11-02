from django.test import TestCase, override_settings
from django.urls import reverse

from . import scoring
from .models import Equipo, Jugador, Partida, StatsJugador

ROLES = ['TOP', 'JGL', 'MID', 'ADC', 'SUP']


def _limpiar_caches():
    scoring._cache_ref.update(clave=None, datos=None)
    scoring._cache_aj.update(clave=None, datos=None)


def crear_partida(match_id='EUW1_TEST', jornada='1', gana_azul=True, mejora=0):
    """Una partida inventada: el equipo azul juega algo mejor que el rojo."""
    azul, _ = Equipo.objects.get_or_create(nombre='KB AZUL')
    rojo, _ = Equipo.objects.get_or_create(nombre='KB ROJO')
    p = Partida.objects.create(
        match_id=match_id, jornada=jornada, numero_partida='1',
        equipo_azul=azul, equipo_rojo=rojo, ganador_equipo=azul if gana_azul else rojo,
        duracion_segundos=1800, dragones_azul=3, dragones_rojo=1, barones_azul=1,
    )
    for lado, equipo, extra in (('a', azul, 2 + mejora), ('r', rojo, 0)):
        for i, rol in enumerate(ROLES):
            j, _ = Jugador.objects.get_or_create(nombre=f'Jug{lado}{i}#TST', defaults={'equipo': equipo})
            StatsJugador.objects.create(
                partida=p, jugador=j, campeon=f'Camp{lado}{i}', rol=rol, equipo_nombre=equipo.nombre,
                kills=3 + extra, muertes=4, asistencias=6 + extra, kda=2.0, kp_porcentaje=50 + 5 * extra,
                oro_min=380 + 10 * extra, dano_infligido=15000, porcentaje_dano_equipo=20, dano_min=600 + 20 * extra,
                dano_recibido=18000, cs=200, cs_min=6.5 + 0.2 * extra, vision_min=1.0, game_time=30.0,
                victoria=(equipo == p.ganador_equipo),
                riot_extra={
                    'champExperience': 14000 + 300 * extra, 'goldEarned': 11000 + 400 * extra,
                    'damageDealtToObjectives': 6000, 'wardsPlaced': 12, 'wardsKilled': 4, 'placas': 2,
                    'challenges': {'dragonTakedowns': 1, 'laneMinionsFirst10Minutes': 60 + extra,
                                   'jungleCsBefore10Minutes': 50 + extra, 'soloKills': 1, 'turretTakedowns': 1},
                },
            )
    return p


class NotaTests(TestCase):
    def setUp(self):
        _limpiar_caches()

    def test_nota_entre_0_y_100_con_puesto_mvp_y_ace(self):
        p = crear_partida()
        res = scoring.puntuar_partida(p)
        self.assertEqual(len(res), 10)
        for r in res.values():
            self.assertGreaterEqual(r['nota'], 0)
            self.assertLessEqual(r['nota'], 100)
            self.assertEqual(len(r['bloques']), 5)
        self.assertEqual(sorted(r['puesto'] for r in res.values()), list(range(1, 11)))
        stats = {s.id: s for s in StatsJugador.objects.filter(partida=p)}
        mvp = [i for i, r in res.items() if r['insignia'] == 'MVP']
        ace = [i for i, r in res.items() if r['insignia'] == 'ACE']
        self.assertEqual(len(mvp), 1)
        self.assertEqual(len(ace), 1)
        self.assertTrue(stats[mvp[0]].victoria)
        self.assertFalse(stats[ace[0]].victoria)

    def test_ganar_suma_seis_puntos(self):
        s = crear_partida().stats_jugadores.get(rol='MID', equipo_nombre='KB ROJO')
        self.assertAlmostEqual(scoring._nota(20, True) - scoring._nota(20, False), scoring.NOTA_VICTORIA)
        self.assertEqual(scoring._nota(500, True), 100)   # tope
        self.assertEqual(scoring._nota(-500, False), 0)   # suelo
        self.assertFalse(s.victoria)

    def test_ajustes_de_rol_se_compensan(self):
        crear_partida('EUW1_A', '1')
        crear_partida('EUW1_B', '2', gana_azul=False)
        ajustes = scoring.ajustes_rol()
        self.assertEqual(set(ajustes), set(ROLES))
        self.assertAlmostEqual(sum(ajustes.values()) / len(ajustes), 0, delta=0.15)

    def test_ranking_y_tiers(self):
        crear_partida('EUW1_A', '1')
        crear_partida('EUW1_B', '2', gana_azul=False)
        ranking = scoring.ranking_jugadores(StatsJugador.objects.select_related('jugador'))
        self.assertEqual(len(ranking), 10)
        self.assertEqual([f['nota'] for f in ranking], sorted((f['nota'] for f in ranking), reverse=True))
        for f in ranking:
            self.assertIn(f['tier'], ['S+', 'S', 'A', 'B', 'C', 'D'])
            self.assertEqual(f['partidas'], 2)


@override_settings(ALLOWED_HOSTS=['testserver'])
class PaginasTests(TestCase):
    def setUp(self):
        _limpiar_caches()
        self.p = crear_partida()

    def test_paginas_principales_cargan(self):
        urls = [
            reverse('index'), reverse('partidas'), reverse('jugadores'), reverse('tier_list'),
            reverse('clasificacion_grupos'), reverse('detalle_partida', args=[self.p.match_id]),
            reverse('jugador', args=['Juga0#TST']), reverse('equipo', args=['KB AZUL']),
            reverse('buscar') + '?q=zzz',
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url, HTTP_ACCEPT='text/html')
                self.assertEqual(r.status_code, 200)

    def test_jugadores_pestanas_orden_y_minimo(self):
        url = reverse('jugadores')
        r = self.client.get(url, {'vista': 'combate', 'sort': 'd_pg', 'order': 'asc'})
        self.assertEqual(r.context['vista'], 'combate')
        muertes = [j['d_pg'] for j in r.context['jugadores']]
        self.assertEqual(muertes, sorted(muertes))
        self.assertTrue(all(len(j['celdas']) == len(r.context['columnas']) for j in r.context['jugadores']))
        # Pestaña o columna desconocidas: valores por defecto
        r = self.client.get(url, {'vista': 'xx', 'sort': 'xx', 'min': 'x'})
        self.assertEqual((r.context['vista'], r.context['sort_activo'], r.context['minimo']), ('resumen', 'nota', 1))
        # Nadie tiene 2 partidas en los datos de prueba
        r = self.client.get(url, {'min': 2})
        self.assertEqual(r.context['jugadores'], [])
        # MVP y ACE: uno de cada en la partida de prueba, y se puede ordenar por ellos
        js = self.client.get(url, {'sort': 'mvp'}).context['jugadores']
        self.assertEqual((js[0]['mvp'], sum(j['mvp'] for j in js), sum(j['ace'] for j in js)), (1, 1, 1))

    def test_tier_list_minimo_de_partidas(self):
        url = reverse('tier_list')
        self.assertEqual(len(self.client.get(url).context['ranking']), 10)
        r = self.client.get(url, {'min': 2})   # en los datos de prueba todos tienen 1 partida
        self.assertEqual((r.context['ranking'], r.context['minimo']), ([], 2))
        self.assertEqual(self.client.get(url, {'min': 'x'}).context['minimo'], 1)

    def test_tier_list_mas_mvp_y_ace(self):
        premios = {p['clave']: p['filas'] for p in self.client.get(reverse('tier_list')).context['premios']}
        # Una partida: un MVP (equipo azul, que gana) y un ACE (equipo rojo)
        self.assertEqual([(f['n'], f['equipo']) for f in premios['MVP']], [(1, 'KB AZUL')])
        self.assertEqual([(f['n'], f['equipo']) for f in premios['ACE']], [(1, 'KB ROJO')])
        self.assertEqual(self.client.get(reverse('tier_list'), {'min': 2}).context['premios'][0]['filas'], [])

    def test_grafica_de_oro(self):
        from .utils import curvas_por_participante
        # Timeline mínimo: 3 frames; el jugador 2 falta en el segundo (se repite su último valor)
        frames = [
            {'timestamp': 0, 'participantFrames': {'1': {'totalGold': 500}, '2': {'totalGold': 500}}},
            {'timestamp': 60010, 'participantFrames': {'1': {'totalGold': 900, 'minionsKilled': 4}}},
            {'timestamp': 95000, 'participantFrames': {'1': {'totalGold': 1300}, '2': {'totalGold': 1000}}},
        ]
        c = curvas_por_participante({'info': {'frames': frames}})
        self.assertEqual(c[1]['frames_s'], [0, 60, 95])
        self.assertEqual(c[1]['cs_t'], [0, 4, 0])
        self.assertEqual(c[2]['oro_t'], [500, 500, 1000])

        url = reverse('detalle_partida', args=[self.p.match_id])
        # Sin datos del timeline no hay gráfica
        self.assertIsNone(self.client.get(url, HTTP_ACCEPT='text/html').context['oro_grafica'])
        for s in self.p.stats_jugadores.all():
            base = 1000 if s.equipo_nombre == 'KB AZUL' else 900
            s.riot_extra = dict(s.riot_extra, frames_s=[0, 60, 95], oro_t=[500, base, base + 100])
            s.save()
        r = self.client.get(url, HTTP_ACCEPT='text/html')
        g = r.context['oro_grafica']
        self.assertEqual(g['equipos']['azul']['oro'], [2500, 5000, 5500])
        self.assertEqual(g['equipos']['rojo']['oro'], [2500, 4500, 5000])
        self.assertEqual(list(g['roles']), ROLES)
        self.assertContains(r, 'id="oro-plot"')

    def test_buscador_json(self):
        r = self.client.get(reverse('buscar'), {'q': 'Juga', 'format': 'json'})
        datos = r.json()
        self.assertEqual(len(datos['jugadores']), 5)
        self.assertTrue(all(j['url'].startswith('/jugador/') for j in datos['jugadores']))

    def test_buscador_con_un_resultado_redirige(self):
        r = self.client.get(reverse('buscar'), {'q': 'Juga0'})
        self.assertRedirects(r, reverse('jugador', args=['Juga0#TST']))


@override_settings(ALLOWED_HOSTS=['testserver'])
class TemporadasTests(TestCase):
    """Dos temporadas: la 1 sin grupos (una sola tabla) y la 2 con grupo."""

    def setUp(self):
        from .models import Temporada
        _limpiar_caches()
        self.t1 = Temporada.objects.create(slug='t1', nombre='Temporada 1', orden=1)
        self.t2 = Temporada.objects.create(slug='t2', nombre='Temporada 2', orden=2,
                                           grupos=[{'nombre': 'SOL', 'equipos': ['KB AZUL', 'KB ROJO']}])
        self.p1 = crear_partida('EUW1_T1', jornada='SUIZO 1')
        self.p1b = crear_partida('EUW1_T1B', jornada='PLAYOFFS CUARTOS', gana_azul=False)
        self.p2 = crear_partida('EUW1_T2', jornada='1')
        Partida.objects.filter(match_id__in=['EUW1_T1', 'EUW1_T1B']).update(temporada=self.t1)
        Partida.objects.filter(match_id='EUW1_T2').update(temporada=self.t2)

    def test_por_defecto_la_mas_reciente_y_se_puede_cambiar(self):
        r = self.client.get(reverse('partidas'))
        self.assertEqual((r.context['temporada'], r.context['total_partidas']), (self.t2, 1))
        r = self.client.get(reverse('partidas'), {'temporada': 't1'})
        self.assertEqual((r.context['temporada'], r.context['total_partidas']), (self.t1, 2))
        # La elección se queda en la sesión para el resto de páginas
        r = self.client.get(reverse('jugadores'))
        self.assertEqual(r.context['temporada'], self.t1)
        self.assertEqual(r.context['jugadores'][0]['games_played'], 2)
        self.assertContains(r, 'id="sel-temporada"')

    def test_clasificacion_sin_grupos_y_sin_playoffs(self):
        r = self.client.get(reverse('clasificacion_grupos'), {'temporada': 't1'})
        (tabla,) = r.context['clasificaciones']
        self.assertEqual(tabla['grupo'], 'Liga')
        # Los cuartos (que gana el rojo) no cuentan
        self.assertEqual({e['equipo']: e['victorias'] for e in tabla['equipos']}, {'KB AZUL': 1, 'KB ROJO': 0})
        r = self.client.get(reverse('clasificacion_grupos'), {'temporada': 't2'})
        self.assertEqual([g['grupo'] for g in r.context['clasificaciones']], ['SOL'])

    def test_perfil_con_varias_temporadas(self):
        url = reverse('jugador', args=['Juga0#TST'])
        r = self.client.get(url)
        self.assertEqual((r.context['temporada_vista'], r.context['resumen']['partidas']), (self.t2, 1))
        self.assertEqual(r.context['temporadas_propias'], [self.t2, self.t1])
        r = self.client.get(url, {'temporada': 'todas'})
        self.assertEqual((r.context['ver_todas'], r.context['resumen']['partidas']), (True, 3))

    def test_orden_y_nombre_de_jornadas(self):
        from .templatetags.kb import jornada_txt
        from .views import orden_jornada
        orden = sorted(['FINAL', 'SUIZO 2', '10', 'PLAYOFFS SEMIFINAL', '2', 'PLAYOFFS CUARTOS', 'SUIZO 1'], key=orden_jornada)
        self.assertEqual(orden, ['2', '10', 'SUIZO 1', 'SUIZO 2', 'PLAYOFFS CUARTOS', 'PLAYOFFS SEMIFINAL', 'FINAL'])
        self.assertEqual([jornada_txt(j) for j in ('SUIZO 1', 'PLAYOFFS CUARTOS', 'FINAL')], ['Suizo 1', 'Cuartos', 'Final'])
