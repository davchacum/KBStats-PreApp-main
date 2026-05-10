from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0005_statsjugador_dano_oro'),
    ]

    operations = [
        migrations.AddField(
            model_name='statsjugador',
            name='wpm',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='statsjugador',
            name='cwpm',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='statsjugador',
            name='wcpm',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='statsjugador',
            name='gold_pct',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='statsjugador',
            name='death_share',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='statsjugador',
            name='victoria',
            field=models.BooleanField(default=False),
        ),
    ]
