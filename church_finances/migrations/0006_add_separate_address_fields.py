# Generated manually to add separate address fields to ChurchMember model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('church_finances', '0005_church_subscription_status_church_subscription_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='churchmember',
            name='street_address',
            field=models.CharField(blank=True, max_length=255, verbose_name='Street Address'),
        ),
        migrations.AddField(
            model_name='churchmember',
            name='city',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='churchmember',
            name='state',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='churchmember',
            name='zip_code',
            field=models.CharField(blank=True, max_length=20, verbose_name='ZIP/Postal Code'),
        ),
        migrations.AddField(
            model_name='churchmember',
            name='country',
            field=models.CharField(blank=True, default='United States', max_length=100),
        ),
    ]