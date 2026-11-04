from django.db import migrations, models
from django.db.models import Q


def remove_export_records(apps, schema_editor):
    FreightRate = apps.get_model("cotizador", "FreightRate")
    QuoteHistory = apps.get_model("cotizador", "QuoteHistory")
    Route = apps.get_model("cotizador", "Route")
    database = schema_editor.connection.alias

    rate_ids = set(
        FreightRate.objects.using(database)
        .filter(Q(operation="export") | Q(route__country="Chile"))
        .values_list("pk", flat=True)
    )
    QuoteHistory.objects.using(database).filter(
        Q(operation="export") | Q(rate_id__in=rate_ids)
    ).delete()
    FreightRate.objects.using(database).filter(pk__in=rate_ids).delete()
    Route.objects.using(database).filter(
        country="Chile",
        rates__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cotizador", "0008_quotehistory_rate_amounts"),
    ]

    operations = [
        migrations.RunPython(remove_export_records, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="freightrate",
            name="operation",
            field=models.CharField(
                choices=[("import", "Importación")],
                default="import",
                max_length=6,
            ),
        ),
        migrations.AlterField(
            model_name="quotehistory",
            name="operation",
            field=models.CharField(
                choices=[("import", "Importación")],
                max_length=6,
            ),
        ),
        migrations.AddConstraint(
            model_name="freightrate",
            constraint=models.CheckConstraint(
                condition=Q(operation="import"),
                name="freightrate_import_only",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotehistory",
            constraint=models.CheckConstraint(
                condition=Q(operation="import"),
                name="quotehistory_import_only",
            ),
        ),
    ]
