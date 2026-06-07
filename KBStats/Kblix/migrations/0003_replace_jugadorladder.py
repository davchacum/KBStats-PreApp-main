from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Kblix', '0002_ladder'),
    ]

    operations = [
        migrations.DeleteModel(name='JugadorLadder'),
        migrations.CreateModel(
            name='LadderPlayer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre',      models.CharField(max_length=100, unique=True)),
                ('riot_id',     models.CharField(blank=True, max_length=100)),
                ('puuid',       models.CharField(blank=True, max_length=200)),
                ('summoner_id', models.CharField(blank=True, max_length=200)),
                ('rol',    models.CharField(blank=True, choices=[('TOP','Top'),('JUNGLE','Jungla'),('MID','Mid'),('ADC','ADC'),('SUPPORT','Support')], max_length=10)),
                ('equipo', models.CharField(blank=True, max_length=100)),
                ('tier',   models.CharField(blank=True, max_length=20)),
                ('rank',   models.CharField(blank=True, max_length=5)),
                ('lp',     models.IntegerField(default=0)),
                ('wins',   models.IntegerField(default=0)),
                ('losses', models.IntegerField(default=0)),
                ('last_updated', models.DateTimeField(blank=True, null=True)),
            ],
            options={'app_label': 'Kblix', 'ordering': ['nombre']},
        ),
    ]
