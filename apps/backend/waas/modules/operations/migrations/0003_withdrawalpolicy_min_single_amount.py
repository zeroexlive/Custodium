from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0002_platformhalt"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalpolicy",
            name="min_single_amount",
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=78, null=True),
        ),
    ]
