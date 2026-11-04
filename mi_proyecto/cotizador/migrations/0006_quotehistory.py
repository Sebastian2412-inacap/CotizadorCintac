from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cotizador", "0005_remove_freightrate_unique_route_destination_carrier_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuoteHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("operation", models.CharField(choices=[("import", "Importación"), ("export", "Exportación")], max_length=6)),
                ("origin_port", models.CharField(max_length=120)),
                ("origin_country", models.CharField(max_length=80)),
                ("destination", models.CharField(max_length=120)),
                ("carrier", models.CharField(blank=True, max_length=120)),
                ("container_size", models.CharField(max_length=2)),
                ("weight", models.DecimalField(decimal_places=6, max_digits=20)),
                ("weight_unit", models.CharField(max_length=3)),
                ("tonnes", models.DecimalField(decimal_places=6, max_digits=20)),
                ("container_quantity", models.PositiveIntegerField()),
                ("margin_days", models.PositiveIntegerField(default=0)),
                ("source_currency", models.CharField(max_length=3)),
                ("currency", models.CharField(max_length=3)),
                ("exchange_rate", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("amount_max", models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ("base_days", models.PositiveIntegerField()),
                ("base_days_max", models.PositiveIntegerField(blank=True, null=True)),
                ("total_days", models.PositiveIntegerField()),
                ("total_days_max", models.PositiveIntegerField(blank=True, null=True)),
                ("rate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="saved_quotes", to="cotizador.freightrate")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quote_history", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
            },
        ),
    ]
