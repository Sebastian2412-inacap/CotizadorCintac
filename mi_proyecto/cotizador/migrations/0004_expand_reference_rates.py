# Operaciones de esquema y datos para admitir destinos y rangos de referencia.
from django.db import migrations, models
import django.db.models.deletion


# Tarifas de referencia: origen, destino, ruta, rangos de precios y tránsito, fuente.
REFERENCE_RATES = [
    ("China", "Shanghai", "San Antonio", "Directo / Transbordo", 1600, 2800, 2300, 3800, 25, 32, "Segucargo / Delpa Group 2026"),
    ("China", "Shanghai", "Valparaíso", "Directo / Transbordo", 1650, 2850, 2350, 3850, 26, 34, "Segucargo / Delpa Group 2026"),
    ("China", "Ningbo", "San Antonio", "Directo / Transbordo", 1600, 2800, 2300, 3800, 26, 32, "Segucargo / Delpa Group 2026"),
    ("China", "Ningbo", "Valparaíso", "Directo / Transbordo", 1650, 2850, 2350, 3850, 27, 34, "Segucargo / Delpa Group 2026"),
    ("China", "Qingdao", "San Antonio", "Directo / Transbordo", 1700, 2900, 2400, 3900, 28, 34, "Segucargo / Delpa Group 2026"),
    ("China", "Qingdao", "Valparaíso", "Directo / Transbordo", 1750, 2950, 2450, 3950, 29, 36, "Segucargo / Delpa Group 2026"),
    ("China", "Shenzhen / Yantian", "San Antonio", "Directo / Transbordo", 1650, 2850, 2350, 3850, 27, 33, "Segucargo / Delpa Group 2026"),
    ("China", "Shenzhen / Yantian", "Valparaíso", "Directo / Transbordo", 1700, 2900, 2400, 3900, 28, 35, "Segucargo / Delpa Group 2026"),
    ("China", "Tianjin", "San Antonio", "Transbordo", 1800, 3000, 2500, 4000, 30, 36, "Segucargo / Delpa Group 2026"),
    ("China", "Tianjin", "Valparaíso", "Transbordo", 1850, 3050, 2550, 4050, 31, 38, "Segucargo / Delpa Group 2026"),
    ("Corea del Sur", "Busan", "San Antonio", "Transbordo", 1700, 2900, 2400, 3900, 30, 38, "MundoMaritimo / Delpa Group 2026"),
    ("Corea del Sur", "Busan", "Valparaíso", "Transbordo", 1750, 2950, 2450, 3950, 31, 40, "MundoMaritimo / Delpa Group 2026"),
    ("Japón", "Tokio / Yokohama", "San Antonio", "Transbordo", 1900, 3100, 2600, 4100, 32, 40, "Estimado referencial 2026"),
    ("Japón", "Tokio / Yokohama", "Valparaíso", "Transbordo", 1950, 3150, 2650, 4150, 33, 42, "Estimado referencial 2026"),
    ("Vietnam", "Ho Chi Minh", "San Antonio", "Transbordo", 1900, 3200, 2700, 4300, 35, 42, "Estimado referencial 2026"),
    ("Vietnam", "Ho Chi Minh", "Valparaíso", "Transbordo", 1950, 3250, 2750, 4350, 36, 44, "Estimado referencial 2026"),
]


def fix_and_seed(apps, schema_editor):
    # Accede a los modelos históricos correspondientes al estado de esta migración.
    Route = apps.get_model("cotizador", "Route")
    FreightRate = apps.get_model("cotizador", "FreightRate")

    # Las tarifas iniciales del informe están expresadas en US$, no en CLP.
    FreightRate.objects.filter(destination_port="").update(currency="USD")

    # Crea cada ruta y actualiza o inserta su tarifa de referencia de forma repetible.
    for country, origin, destination, route_type, f20_min, f20_max, f40_min, f40_max, days_min, days_max, source in REFERENCE_RATES:
        route, _ = Route.objects.get_or_create(country=country, origin_port=origin)
        FreightRate.objects.update_or_create(
            route=route,
            destination_port=destination,
            carrier="",
            defaults={
                "route_type": route_type,
                "source": source,
                "transit_days": days_min,
                "transit_days_max": days_max,
                "freight_20": f20_min,
                "freight_20_max": f20_max,
                "freight_40": f40_min,
                "freight_40_max": f40_max,
                "currency": "USD",
            },
        )


# Amplía los campos, restricciones y datos admitidos por las tarifas de flete.
class Migration(migrations.Migration):
    # Sigue a la migración que definió las monedas iniciales.
    dependencies = [("cotizador", "0003_alter_freightrate_currency")]

    # Actualiza orden, columnas, restricciones y moneda, y luego incorpora referencias.
    operations = [
        migrations.AlterModelOptions(name="freightrate", options={"ordering": ["route__country", "route__origin_port", "destination_port", "carrier"]}),
        migrations.AddField(model_name="freightrate", name="destination_port", field=models.CharField(blank=True, default="", max_length=120), preserve_default=False),
        migrations.AddField(model_name="freightrate", name="freight_20_max", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="freightrate", name="freight_40_max", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="freightrate", name="route_type", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="freightrate", name="source", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="freightrate", name="transit_days_max", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.RemoveConstraint(model_name="freightrate", name="unique_route_carrier"),
        migrations.AddConstraint(model_name="freightrate", constraint=models.UniqueConstraint(fields=("route", "destination_port", "carrier"), name="unique_route_destination_carrier")),
        migrations.AddConstraint(model_name="freightrate", constraint=models.CheckConstraint(condition=models.Q(("freight_20_max__isnull", True), ("freight_20_max__gte", models.F("freight_20")), _connector="OR"), name="freight_20_max_gte_min")),
        migrations.AddConstraint(model_name="freightrate", constraint=models.CheckConstraint(condition=models.Q(("freight_40_max__isnull", True), ("freight_40_max__gte", models.F("freight_40")), _connector="OR"), name="freight_40_max_gte_min")),
        migrations.AddConstraint(model_name="freightrate", constraint=models.CheckConstraint(condition=models.Q(("transit_days_max__isnull", True), ("transit_days_max__gte", models.F("transit_days")), _connector="OR"), name="transit_days_max_gte_min")),
        migrations.AlterField(model_name="freightrate", name="currency", field=models.CharField(choices=[("CLP", "CLP"), ("USD", "USD")], default="USD", max_length=3)),
        migrations.RunPython(fix_and_seed, migrations.RunPython.noop),
    ]
