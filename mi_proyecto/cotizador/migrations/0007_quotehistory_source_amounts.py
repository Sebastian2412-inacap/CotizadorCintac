from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cotizador", "0006_quotehistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotehistory",
            name="source_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name="quotehistory",
            name="source_amount_max",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
    ]
