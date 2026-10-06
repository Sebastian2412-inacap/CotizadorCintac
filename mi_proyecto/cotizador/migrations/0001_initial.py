# Migración inicial generada por Django el 30-09-2026.

# Importa las operaciones y tipos necesarios para crear los modelos iniciales.
import django.db.models.deletion
from django.db import migrations, models


# Define el estado inicial de la base de datos para la aplicación cotizador.
class Migration(migrations.Migration):

    # Esta migración no depende de otras migraciones de la aplicación.
    initial = True

    dependencies = [
    ]

    # Crea las tablas Route y FreightRate con sus campos e índices iniciales.
    operations = [
        # Tabla de rutas de origen.
        migrations.CreateModel(
            name='Route',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country', models.CharField(max_length=80)),
                ('origin_port', models.CharField(max_length=120)),
            ],
            options={
                'ordering': ['country', 'origin_port'],
                'constraints': [models.UniqueConstraint(fields=('country', 'origin_port'), name='unique_origin_country_port')],
            },
        ),
        # Tabla de tarifas asociadas a una ruta.
        migrations.CreateModel(
            name='FreightRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('carrier', models.CharField(blank=True, max_length=120)),
                ('transit_days', models.PositiveIntegerField()),
                ('freight_20', models.DecimalField(decimal_places=2, max_digits=14)),
                ('freight_40', models.DecimalField(decimal_places=2, max_digits=14)),
                ('currency', models.CharField(blank=True, choices=[('', 'Moneda pendiente'), ('CLP', 'CLP'), ('USD', 'USD')], max_length=3)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rates', to='cotizador.route')),
            ],
            options={
                'ordering': ['route__country', 'route__origin_port', 'carrier'],
                'constraints': [models.UniqueConstraint(fields=('route', 'carrier'), name='unique_route_carrier'), models.CheckConstraint(condition=models.Q(('freight_20__gte', 0)), name='freight_20_non_negative'), models.CheckConstraint(condition=models.Q(('freight_40__gte', 0)), name='freight_40_non_negative')],
            },
        ),
    ]
