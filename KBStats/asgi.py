import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
import KBStats.Kblix.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KBStats.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': URLRouter(
        KBStats.Kblix.routing.websocket_urlpatterns
    ),
})
