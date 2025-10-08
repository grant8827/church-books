# Generated manually for removing premium subscription type

from django.db import migrations

def update_premium_to_standard(apps, schema_editor):
    """Update any existing premium subscriptions to standard"""
    Church = apps.get_model('church_finances', 'Church')
    Church.objects.filter(subscription_type='premium').update(subscription_type='standard')

def reverse_update(apps, schema_editor):
    """Reverse migration - not applicable since we're removing premium"""
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('church_finances', '0005_church_subscription_status_church_subscription_type'),
    ]

    operations = [
        migrations.RunPython(update_premium_to_standard, reverse_update),
    ]