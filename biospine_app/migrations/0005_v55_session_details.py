from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('biospine_app', '0004_v51_body_metrics'),
    ]

    operations = [
        migrations.AddField(model_name='userprofile', name='extras', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='posturesession', name='client_id', field=models.CharField(blank=True, default='', max_length=40)),
        migrations.AddField(model_name='posturesession', name='started_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='ended_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='source', field=models.CharField(blank=True, default='device', max_length=12)),
        migrations.AddField(model_name='posturesession', name='mode', field=models.CharField(blank=True, default='', max_length=12)),
        migrations.AddField(model_name='posturesession', name='warning_angle', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='median_dev', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='max_dev', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='avg_roll', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='max_roll', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='peak_load', field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='strain', field=models.JSONField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='trend', field=models.JSONField(blank=True, null=True)),
        migrations.AddField(model_name='posturesession', name='events', field=models.JSONField(blank=True, null=True)),
        migrations.AddConstraint(
            model_name='posturesession',
            constraint=models.UniqueConstraint(condition=models.Q(('client_id', ''), _negated=True), fields=('user', 'client_id'), name='uniq_session_client_id'),
        ),
    ]
