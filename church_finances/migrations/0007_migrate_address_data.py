# Data migration to migrate existing address data to new separate fields

from django.db import migrations
import re


def migrate_existing_addresses(apps, schema_editor):
    """
    Migrate existing address data from the single address field to separate fields
    """
    ChurchMember = apps.get_model('church_finances', 'ChurchMember')
    
    for member in ChurchMember.objects.all():
        if member.address and not member.street_address:
            # Try to parse the existing address
            lines = member.address.strip().split('\n')
            if lines:
                # First line is usually street address
                member.street_address = lines[0].strip()
                
                # Try to parse city, state, zip from the last line
                if len(lines) > 1:
                    last_line = lines[-1].strip()
                    
                    # Look for patterns like "City, ST 12345" or "City, State 12345"
                    pattern = r'^(.+),\s*([A-Za-z\s]+)\s+(\d{5}(?:-\d{4})?)$'
                    match = re.match(pattern, last_line)
                    
                    if match:
                        member.city = match.group(1).strip()
                        member.state = match.group(2).strip()
                        member.zip_code = match.group(3).strip()
                    else:
                        # If pattern doesn't match, just put the whole line as city
                        member.city = last_line
                
                member.save()


def reverse_migration(apps, schema_editor):
    """
    Reverse migration - combine separate fields back into single address field
    """
    ChurchMember = apps.get_model('church_finances', 'ChurchMember')
    
    for member in ChurchMember.objects.all():
        if member.street_address or member.city or member.state or member.zip_code:
            address_parts = []
            
            if member.street_address:
                address_parts.append(member.street_address)
            
            city_state_zip = []
            if member.city:
                city_state_zip.append(member.city)
            if member.state:
                city_state_zip.append(member.state)
            if member.zip_code:
                city_state_zip.append(member.zip_code)
            
            if city_state_zip:
                address_parts.append(', '.join(city_state_zip))
            
            if member.country and member.country.lower() != 'united states':
                address_parts.append(member.country)
            
            member.address = '\n'.join(address_parts)
            member.save()


class Migration(migrations.Migration):

    dependencies = [
        ('church_finances', '0006_add_separate_address_fields'),
    ]

    operations = [
        migrations.RunPython(migrate_existing_addresses, reverse_migration),
    ]