from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Cinturones', '0007_partida_position_data'),
    ]

    operations = [
        migrations.AddField(model_name='statsjugador', name='gd15',  field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='csd15', field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='xpd15', field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='cs15',  field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='ka15',  field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='fb',    field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name='statsjugador', name='fbv',   field=models.BooleanField(blank=True, null=True)),
    ]
