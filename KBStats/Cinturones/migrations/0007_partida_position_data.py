from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0006_statsjugador_advanced_metrics'),
    ]

    operations = [
        migrations.AddField(
            model_name='partida',
            name='position_data',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
