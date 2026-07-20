from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('church_finances', '0037_managedpaymentgateway_wipay_credentials')]

    operations = [
        migrations.AddField(
            model_name='managedpaymentgateway', name='paypal_payment_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='managedpaymentgateway', name='stripe_payment_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.CreateModel(
            name='HostedDonationAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('paypal', 'PayPal'), ('stripe', 'Stripe')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('contribution_type', models.CharField(choices=[('tithe', 'Tithe'), ('offering', 'Offering'), ('special_offering', 'Special Offering'), ('building_fund', 'Building Fund'), ('missions', 'Missions'), ('other', 'Other')], max_length=20)),
                ('donor_name', models.CharField(blank=True, max_length=100)),
                ('donor_email', models.EmailField(blank=True, max_length=254)),
                ('status', models.CharField(choices=[('pending', 'Pending verification'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')], db_index=True, default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('church', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hosted_donation_attempts', to='church_finances.church')),
                ('contribution', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='hosted_payment_attempt', to='church_finances.contribution')),
            ],
            options={'db_table': 'cb_hosted_donation_attempts', 'ordering': ['-created_at']},
        ),
    ]
