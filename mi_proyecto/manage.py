#!/usr/bin/env python
# Indica al sistema que ejecute este archivo con Python.
"""Utilidad de línea de comandos de Django para tareas administrativas."""
import os  # Permite configurar variables de entorno del proceso.
import sys  # Proporciona los argumentos recibidos desde la línea de comandos.


def main():
    """Prepara y ejecuta las tareas administrativas de Django."""
    # Define el módulo de configuración de Django si aún no está configurado.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        # Importa la función de Django que interpreta y ejecuta los comandos.
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # Explica el problema si Django no está instalado o no se encuentra.
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Entrega a Django los argumentos escritos al ejecutar manage.py.
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    # Ejecuta main solo cuando este archivo se inicia directamente.
    main()
