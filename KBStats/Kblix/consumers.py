import asyncio
import json
import random
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from .models import Jugador, Equipo

TURN_TIME = 15

game_states = {}


class GameConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group = f'kblix_game_{self.room_id}'

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        if self.room_id not in game_states:
            game_states[self.room_id] = {
                'players': [],
                'cadena': [],
                'nombres': [],
                'turno': None,
                'timer_task': None,
                'started': False,
            }

        state = game_states[self.room_id]

        if len(state['players']) >= 2:
            await self.send(json.dumps({'type': 'error', 'msg': 'Sala llena'}))
            await self.close()
            return

        state['players'].append(self.channel_name)

        if len(state['players']) == 1:
            await self.send(json.dumps({'type': 'esperando', 'msg': 'Esperando al oponente...'}))
        else:
            await self._start_game()

    async def disconnect(self, close_code):
        state = game_states.get(self.room_id)
        if state and state['started']:
            if state.get('timer_task'):
                state['timer_task'].cancel()
            await self.channel_layer.group_send(
                self.room_group,
                {'type': 'game_over', 'ganador': None, 'razon': 'El oponente se ha desconectado'}
            )

        if self.room_id in game_states:
            del game_states[self.room_id]

        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data.get('type') == 'rematch':
            room_id = data.get('room_id', '')
            if room_id:
                await self.channel_layer.group_send(
                    self.room_group,
                    {'type': 'rematch_game', 'room_id': room_id}
                )
            return

        state = game_states.get(self.room_id)

        if not state or not state['started']:
            return

        if state['turno'] != self.channel_name:
            await self.send(json.dumps({'type': 'error', 'msg': 'No es tu turno'}))
            return

        nombre = data.get('nombre', '').strip()
        if not nombre:
            return

        jugador_anterior_id = state['cadena'][-1]
        valido, jugador_id, jugador_nombre = await self._validar(nombre, jugador_anterior_id, state['cadena'])

        if valido:
            if state['timer_task']:
                state['timer_task'].cancel()

            state['cadena'].append(jugador_id)
            state['nombres'].append(jugador_nombre)

            players = state['players']
            siguiente = players[1] if state['turno'] == players[0] else players[0]
            state['turno'] = siguiente

            await self.channel_layer.group_send(
                self.room_group,
                {'type': 'jugada_valida', 'nombre': jugador_nombre, 'turno': siguiente}
            )

            state['timer_task'] = asyncio.ensure_future(self._timeout())
        else:
            await self.send(json.dumps({
                'type': 'invalido',
                'msg': f'"{nombre}" no es válido. Debe ser un jugador que haya coincidido con el anterior.'
            }))

    async def _start_game(self):
        state = game_states[self.room_id]
        state['started'] = True

        jugador = await self._jugador_aleatorio()
        state['cadena'] = [jugador.id]
        state['nombres'] = [jugador.nombre]
        state['turno'] = state['players'][0]

        await self.channel_layer.group_send(
            self.room_group,
            {'type': 'game_start', 'jugador_inicial': jugador.nombre, 'turno': state['players'][0]}
        )

        state['timer_task'] = asyncio.ensure_future(self._timeout())

    async def _timeout(self):
        await asyncio.sleep(TURN_TIME)
        state = game_states.get(self.room_id)
        if not state:
            return
        perdedor = state['turno']
        players = state['players']
        ganador = players[1] if perdedor == players[0] else players[0]
        opciones = await self._opciones_validas(state['cadena'][-1], state['cadena'])
        await self.channel_layer.group_send(
            self.room_group,
            {'type': 'game_over', 'ganador': ganador, 'razon': 'tiempo', 'opciones': opciones}
        )

    @sync_to_async
    def _opciones_validas(self, jugador_id, cadena_ids):
        companeros = Jugador.objects.filter(
            equipos__jugadores__id=jugador_id
        ).exclude(id__in=cadena_ids).exclude(id=jugador_id).distinct()
        muestra = random.sample(list(companeros), min(3, len(companeros)))
        return [j.nombre for j in muestra]

    @sync_to_async
    def _validar(self, nombre, jugador_anterior_id, cadena_ids):
        jugador = Jugador.objects.filter(nombre__iexact=nombre).first()
        if jugador is None:
            return False, None, None

        if jugador.id in cadena_ids:
            return False, None, None

        coinciden = Equipo.objects.filter(
            jugadores__id=jugador_anterior_id
        ).filter(jugadores__id=jugador.id).exists()

        return coinciden, jugador.id if coinciden else None, jugador.nombre if coinciden else None

    @sync_to_async
    def _jugador_aleatorio(self):
        return Jugador.objects.filter(
            equipos__temporada__nombre__in=['Sprint 4', 'Split 3']
        ).distinct().order_by('?').first()

    async def game_start(self, event):
        state = game_states.get(self.room_id, {})
        await self.send(json.dumps({
            'type': 'start',
            'jugador_inicial': event['jugador_inicial'],
            'mi_turno': event['turno'] == self.channel_name,
            'tiempo': TURN_TIME,
        }))

    async def jugada_valida(self, event):
        state = game_states.get(self.room_id, {})
        await self.send(json.dumps({
            'type': 'valido',
            'nombre': event['nombre'],
            'mi_turno': event['turno'] == self.channel_name,
            'cadena': state.get('nombres', []),
            'tiempo': TURN_TIME,
        }))

    async def game_over(self, event):
        ganador = event.get('ganador')
        gane = ganador == self.channel_name if ganador else None
        state = game_states.get(self.room_id, {})
        await self.send(json.dumps({
            'type': 'fin',
            'gane': gane,
            'razon': event['razon'],
            'cadena': state.get('nombres', []),
            'opciones': event.get('opciones', []),
        }))

    async def rematch_game(self, event):
        await self.send(json.dumps({
            'type': 'rematch',
            'room_id': event['room_id'],
        }))


class LadderConsumer(AsyncWebsocketConsumer):
    """Empuja actualizaciones del ladder a todos los clientes conectados."""
    GROUP = 'ladder_updates'

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP, self.channel_name)

    # El nombre del método = type del evento con '.' → '_'
    async def ladder_update(self, event):
        await self.send(text_data=json.dumps({
            'progress': event['progress'],
            'total':    event['total'],
            'nombre':   event.get('nombre', ''),
            'done':     event.get('done', False),
        }))
