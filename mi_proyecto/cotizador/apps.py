# Clases base para registrar la aplicación en la configuración de Django.
from django.apps import AppConfig


# Configuración identificadora de la aplicación cotizador.
class CotizadorConfig(AppConfig):
    # Nombre del paquete que Django debe cargar.
    name = 'cotizador'
