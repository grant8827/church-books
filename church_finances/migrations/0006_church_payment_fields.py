from django.db import migrations, models
import django.conf
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('church_finances', '0005_church_subscription_status_church_subscription_type'),
        migrations.swappable_dependency('auth.User'),
    ]

    operations = [
        migrations.AddField(
            model_name='church',
            name='payment_method',
            field=models.CharField(choices=[('paypal', 'PayPal'), ('offline', 'Offline')], default='offline', max_length=20),
        ),
        migrations.AddField(
            model_name='church',
            name='offline_payment_reference',
            field=models.CharField(blank=True, help_text='Reference # / receipt / memo for offline payment', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='church',
            name='offline_verified_by',
            field=models.ForeignKey(blank=True, help_text='Admin user who verified offline payment', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='offline_verifications', to='auth.user'),
        ),
        migrations.AddField(
            model_name='church',
            name='offline_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='church',
            name='offline_notes',
            field=models.TextField(blank=True, help_text='Internal notes regarding offline payment verification'),
        ),
    ]
