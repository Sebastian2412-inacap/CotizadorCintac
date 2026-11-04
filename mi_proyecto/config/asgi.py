"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

# Permite configurar el entorno que usará Django al iniciar el servidor.
import os

# Fábrica de la aplicación compatible con servidores ASGI.
from django.core.asgi import get_asgi_application

# Usa la configuración del proyecto si el entorno no definió otra.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Objeto que el servidor ASGI invoca para atender solicitudes.
application = get_asgi_application()
