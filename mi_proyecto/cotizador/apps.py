# Clases base para registrar la aplicación en la configuración de Django.
from django.apps import AppConfig
from importlib import import_module


# Configuración identificadora de la aplicación cotizador.
class CotizadorConfig(AppConfig):
    # Nombre del paquete que Django debe cargar.
    name = 'cotizador'

    def ready(self):
        import_module('.signals', package=self.name)
