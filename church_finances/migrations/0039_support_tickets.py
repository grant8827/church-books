from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('church_finances', '0038_hosted_payment_links'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupportTicket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('pricing', 'Pricing question'), ('account_error', 'Account error'), ('login_problem', 'Login problem'), ('payment', 'Payment or subscription'), ('feature_help', 'Help using a feature'), ('bug', 'Something is not working'), ('other', 'Other technical support')], max_length=30)),
                ('subject', models.CharField(max_length=150)),
                ('message', models.TextField()),
                ('contact_email', models.EmailField(max_length=254)),
                ('status', models.CharField(choices=[('open', 'Open'), ('answered', 'Answered'), ('closed', 'Closed')], db_index=True, default='open', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('church', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_tickets', to='church_finances.church')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='support_tickets', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'cb_support_tickets', 'ordering': ['-updated_at']},
        ),
        migrations.CreateModel(
            name='SupportTicketReply',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField()),
                ('email_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('replied_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_replies', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='replies', to='church_finances.supportticket')),
            ],
            options={'db_table': 'cb_support_ticket_replies', 'ordering': ['created_at']},
        ),
    ]
