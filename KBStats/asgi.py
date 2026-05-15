import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KBStats.settings')

from django.core.asgi import get_asgi_application

# Llamar aquí para que Django inicialice el app registry antes de importar
# cualquier módulo que use modelos (routing → consumers → models).
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
import KBStats.Kblix.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(
        KBStats.Kblix.routing.websocket_urlpatterns
    ),
})
