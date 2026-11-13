from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("indexing", "0001_initial"),
        ("projects", "0002_project_withdrawal_allowlist_required"),
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DepositPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("min_amount", models.DecimalField(decimal_places=0, default=0, max_digits=78)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deposit_policies", to="assets.asset")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deposit_policies", to="projects.project")),
            ],
        ),
        migrations.AddConstraint(
            model_name="depositpolicy",
            constraint=models.UniqueConstraint(fields=("project", "asset"), name="uniq_deposit_policy_per_asset"),
        ),
    ]
