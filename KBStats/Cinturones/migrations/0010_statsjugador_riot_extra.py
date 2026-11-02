from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0009_posiciones_cada_10s'),
    ]

    operations = [
        migrations.AddField(
            model_name='statsjugador',
            name='riot_extra',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
