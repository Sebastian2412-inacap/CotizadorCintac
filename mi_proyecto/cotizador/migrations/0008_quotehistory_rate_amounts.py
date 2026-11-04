from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cotizador", "0007_quotehistory_source_amounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotehistory",
            name="rate_currency",
            field=models.CharField(blank=True, max_length=3),
        ),
        migrations.AddField(
            model_name="quotehistory",
            name="rate_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name="quotehistory",
            name="rate_amount_max",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
    ]
