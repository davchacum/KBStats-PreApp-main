"""Filtros de plantilla de KBStats: iconos del juego, notas, nombres y roles."""
from urllib.parse import quote

from django import template
from django.conf import settings
from django.templatetags.static import static

from KBStats.Cinturones.ddragon import HECHIZOS, RUNAS
from KBStats.Cinturones.scoring import color_nota

register = template.Library()

DDRAGON = 'https://ddragon.leagueoflegends.com/cdn'


@register.filter
def icono_perfil(icon_id):
    """Icono de invocador (Data Dragon)."""
    if icon_id in (None, ''):
        return ''
    return f'{DDRAGON}/{settings.DDRAGON_VERSION}/img/profileicon/{icon_id}.png'


@register.filter
def icono_objeto(item_id):
    """Icono de objeto; vacío si el hueco no tiene objeto."""
    if not item_id:
        return ''
    return f'{DDRAGON}/{settings.DDRAGON_VERSION}/img/item/{item_id}.png'


@register.filter
def icono_hechizo(spell_id):
    h = HECHIZOS.get(spell_id)
    return f'{DDRAGON}/{settings.DDRAGON_VERSION}/img/spell/{h[0]}' if h else ''


@register.filter
def nombre_hechizo(spell_id):
    h = HECHIZOS.get(spell_id)
    return h[1] if h else ''


@register.filter
def icono_runa(runa_id):
    r = RUNAS.get(runa_id)
    return f'{DDRAGON}/img/{r[0]}' if r else ''


@register.filter
def nombre_runa(runa_id):
    r = RUNAS.get(runa_id)
    return r[1] if r else ''


@register.filter
def emblema_rango(tier):
    """Emblema de rango de SoloQ (iron ... challenger, o unranked)."""
    t = (tier or '').lower()
    if t not in ('iron', 'bronze', 'silver', 'gold', 'platinum', 'emerald', 'diamond', 'master', 'grandmaster', 'challenger'):
        t = 'unranked'
    return static(f'images/rangos/{t}.svg')

ROL_CORTO = {'TOP': 'TOP', 'JGL': 'JG', 'JUNGLE': 'JG', 'MID': 'MID', 'ADC': 'ADC', 'SUP': 'SUP', 'SUPPORT': 'SUP'}
ROL_LARGO = {'TOP': 'Top', 'JGL': 'Jungla', 'JUNGLE': 'Jungla', 'MID': 'Mid', 'ADC': 'ADC', 'SUP': 'Support', 'SUPPORT': 'Support'}


@register.filter
def icono_campeon(nombre):
    """URL del icono cuadrado de un campeón en Data Dragon."""
    if not nombre:
        return ''
    return f'https://ddragon.leagueoflegends.com/cdn/{settings.DDRAGON_VERSION}/img/champion/{quote(nombre)}.png'


@register.filter
def jornada_txt(jornada, largo=False):
    """'3' → 'J3' ('Jornada 3' con largo); 'FINAL' → 'Final'; 'SUIZO 2' → 'Suizo 2'; 'PLAYOFFS CUARTOS' → 'Cuartos'."""
    j = str(jornada or '').strip()
    if j.isdigit():
        return f'Jornada {j}' if largo else f'J{j}'
    if j.upper().startswith('PLAYOFFS '):
        j = j[9:].strip()
    return j.capitalize() or '—'


@register.filter
def tier_clase(tier):
    """'S+' → 'SP' (para la clase CSS tier-SP)."""
    return (tier or 'D').replace('+', 'P')


@register.filter
def nota_clase(nota):
    try:
        return color_nota(float(nota))
    except (TypeError, ValueError):
        return 'n-sin'


@register.filter
def nombre_juego(nombre):
    """'Faker#KR1' → 'Faker'."""
    return (nombre or '').split('#')[0]


@register.filter
def tag_juego(nombre):
    """'Faker#KR1' → '#KR1' (vacío si no hay tag)."""
    partes = (nombre or '').split('#', 1)
    return f'#{partes[1]}' if len(partes) > 1 else ''


@register.filter
def rol_corto(rol):
    return ROL_CORTO.get((rol or '').upper(), rol or '—')


@register.filter
def rol_largo(rol):
    return ROL_LARGO.get((rol or '').upper(), rol or '—')


@register.filter
def rol_clase(rol):
    """Clase CSS de color del rol (rol-TOP, rol-JGL...)."""
    r = (rol or '').upper()
    return {'JUNGLE': 'JGL', 'SUPPORT': 'SUP'}.get(r, r)


@register.filter
def get(d, clave):
    try:
        return d.get(clave)
    except AttributeError:
        return None


@register.filter
def miles(n):
    """12345 → '12,3k'."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return n
    if abs(n) >= 1000:
        return f'{n / 1000:.1f}k'.replace('.', ',')
    return f'{n:.0f}'


@register.filter
def pct(valor, total):
    """Porcentaje de valor sobre total (0-100), para barras."""
    try:
        total = float(total)
        return round(float(valor) / total * 100, 1) if total else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag
def rol(r, modo='icono'):
    """
    Icono oficial del rol.
      {% rol x %}          solo el icono (con el nombre al pasar el ratón)
      {% rol x 'corto' %}  icono + TOP / JG / MID / ADC / SUP
      {% rol x 'largo' %}  icono + Top / Jungla / Mid / ADC / Support
    """
    from django.utils.html import format_html
    clave = rol_clase(r)
    if clave not in ('TOP', 'JGL', 'MID', 'ADC', 'SUP'):
        return ''
    nombre = rol_largo(r)
    if modo == 'icono':
        return format_html('<span class="ico-rol r-{}" title="{}" role="img" aria-label="{}"></span>', clave, nombre, nombre)
    texto = rol_corto(r) if modo == 'corto' else nombre
    return format_html('<span class="rol"><span class="ico-rol r-{}" aria-hidden="true"></span>{}</span>', clave, texto)
