# Operaciones para insertar datos iniciales sin acoplarse a modelos actuales.
from django.db import migrations


# Tarifas reportadas: país, puertos, días de tránsito y precios para 20 y 40 pies.
REPORT_RATES = [
    ("China", ["Shanghai", "Ningbo", "Shenzhen", "Qingdao", "Guangzhou", "Tianjin"], 45, "4300.00", "5700.00"),
    ("Japón", ["Yokohama", "Tokyo", "Nagoya", "Kobe", "Osaka"], 55, "5500.00", "6700.00"),
    ("España", ["Barcelona"], 40, "3200.00", "5500.00"),
    ("EE.UU.", ["Los Angeles"], 35, "2500.00", "4500.00"),
    ("Perú", ["Callao"], 7, "1000.00", "1200.00"),
]


def seed_report_rates(apps, schema_editor):
    # Obtiene las versiones históricas de los modelos vigentes en esta migración.
    Route = apps.get_model("cotizador", "Route")
    FreightRate = apps.get_model("cotizador", "FreightRate")

    # Crea cada ruta y su tarifa inicial solo si todavía no están registradas.
    for country, ports, transit_days, freight_20, freight_40 in REPORT_RATES:
        for origin_port in ports:
            route, _ = Route.objects.get_or_create(
                country=country,
                origin_port=origin_port,
            )
            FreightRate.objects.get_or_create(
                route=route,
                carrier="",
                defaults={
                    "transit_days": transit_days,
                    "freight_20": freight_20,
                    "freight_40": freight_40,
                    "currency": "",
                },
            )


# Migración de datos que carga las tarifas de referencia del informe original.
class Migration(migrations.Migration):
    # Requiere que las tablas iniciales ya hayan sido creadas.
    dependencies = [("cotizador", "0001_initial")]

    # Ejecuta la carga de datos; la operación inversa no elimina registros.
    operations = [
        migrations.RunPython(seed_report_rates, migrations.RunPython.noop),
    ]