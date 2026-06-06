from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0009_scouting_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='scoutedplayer',
            name='preferred_role',
            field=models.CharField(
                blank=True,
                max_length=20,
                choices=[
                    ('',        'Todos los roles'),
                    ('TOP',     'Top'),
                    ('JUNGLE',  'Jungla'),
                    ('MIDDLE',  'Mid'),
                    ('BOTTOM',  'Bot (ADC)'),
                    ('UTILITY', 'Support'),
                ],
            ),
        ),
    ]
