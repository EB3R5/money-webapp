# Chart colors per user: the six series colors as overrides over the defaults (app/chart_colors.py).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0003_api_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='chart_colors',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
