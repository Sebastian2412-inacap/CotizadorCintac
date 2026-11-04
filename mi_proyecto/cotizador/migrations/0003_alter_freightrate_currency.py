# Migración generada por Django el 30-09-2026 para normalizar monedas.

# Importa la API para actualizar datos y modificar campos del esquema.
from django.db import migrations, models


def assign_initial_rates_to_clp(apps, schema_editor):
    # Usa el modelo histórico y asigna CLP a los registros que tenían moneda vacía.
    FreightRate = apps.get_model("cotizador", "FreightRate")
    FreightRate.objects.filter(currency="").update(currency="CLP")


# Actualiza los datos existentes y cambia las opciones predeterminadas de moneda.
class Migration(migrations.Migration):
    # Se ejecuta después de la carga de tarifas de referencia iniciales.
    dependencies = [
        ('cotizador', '0002_seed_report_rates'),
    ]

    # Ejecuta la normalización y restringe monedas a CLP y USD.
    operations = [
        migrations.RunPython(assign_initial_rates_to_clp, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='freightrate',
            name='currency',
            field=models.CharField(choices=[('CLP', 'CLP'), ('USD', 'USD')], default='CLP', max_length=3),
        ),
    ]
