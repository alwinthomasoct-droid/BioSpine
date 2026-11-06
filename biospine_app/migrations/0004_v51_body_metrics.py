from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('biospine_app', '0003_v5_reviews'),
    ]

    operations = [
        migrations.AddField(model_name='userprofile', name='height_cm', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='userprofile', name='weight_kg', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='userprofile', name='body_updated_at', field=models.DateTimeField(blank=True, null=True)),
    ]
