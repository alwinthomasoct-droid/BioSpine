import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('biospine_app', '0002_v4_security_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='review_prompt_done',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='Review',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.PositiveSmallIntegerField(default=5)),
                ('comment', models.TextField(blank=True, default='', max_length=600)),
                ('display_name', models.CharField(blank=True, default='', max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('show_on_home', models.BooleanField(default=False, help_text='Tick to show this review on the public home page.')),
                ('admin_note', models.CharField(blank=True, default='', max_length=200)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='review', to='biospine_app.userprofile')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
