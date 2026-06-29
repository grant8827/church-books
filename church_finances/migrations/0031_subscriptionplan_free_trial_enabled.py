from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('church_finances', '0030_add_deleted_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionplan',
            name='free_trial_enabled',
            field=models.BooleanField(
                default=True,
                help_text='If enabled, new registrations on this plan receive a 30-day free trial.'
            ),
        ),
    ]
