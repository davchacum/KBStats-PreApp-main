import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Kblix', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LadderUpdateState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_request', models.DateTimeField(blank=True, null=True)),
                ('last_update', models.DateTimeField(blank=True, null=True)),
                ('is_updating', models.BooleanField(default=False)),
                ('update_progress', models.IntegerField(default=0)),
                ('total_players', models.IntegerField(default=0)),
            ],
            options={'app_label': 'Kblix'},
        ),
        migrations.CreateModel(
            name='JugadorLadder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('riot_id', models.CharField(blank=True, max_length=100)),
                ('puuid', models.CharField(blank=True, max_length=200)),
                ('summoner_id', models.CharField(blank=True, max_length=200)),
                ('rol', models.CharField(blank=True, choices=[('TOP', 'Top'), ('JUNGLE', 'Jungla'), ('MID', 'Mid'), ('ADC', 'ADC'), ('SUPPORT', 'Support')], max_length=10)),
                ('tier', models.CharField(blank=True, max_length=20)),
                ('rank', models.CharField(blank=True, max_length=5)),
                ('lp', models.IntegerField(default=0)),
                ('wins', models.IntegerField(default=0)),
                ('losses', models.IntegerField(default=0)),
                ('last_updated', models.DateTimeField(blank=True, null=True)),
                ('jugador', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ladder',
                    to='Kblix.jugador',
                )),
            ],
            options={'app_label': 'Kblix'},
        ),
    ]
