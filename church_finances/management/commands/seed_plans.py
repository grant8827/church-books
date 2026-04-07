"""
Management command: seed_plans
Ensures the four SubscriptionPlan rows exist in the database.
Uses get_or_create — safe to run multiple times (idempotent).
"""
from django.core.management.base import BaseCommand
from church_finances.models import SubscriptionPlan


PLANS = [
    {
        "slug": "starter",
        "name": "Starter",
        "member_limit": 50,
        "annual_price": "150.00",
        "is_custom": False,
        "description": "Perfect for small congregations up to 50 members.",
        "is_active": True,
    },
    {
        "slug": "growth",
        "name": "Growth",
        "member_limit": 100,
        "annual_price": "240.00",
        "is_custom": False,
        "description": "Ideal for growing churches up to 100 members.",
        "is_active": True,
    },
    {
        "slug": "community",
        "name": "Community",
        "member_limit": 200,
        "annual_price": "330.00",
        "is_custom": False,
        "description": "Designed for established congregations up to 200 members.",
        "is_active": True,
    },
    {
        "slug": "custom",
        "name": "Custom",
        "member_limit": None,
        "annual_price": "330.00",
        "is_custom": True,
        "description": "For large churches with more than 200 members. Pricing based on congregation size.",
        "is_active": True,
    },
]


class Command(BaseCommand):
    help = "Seed the four SubscriptionPlan rows. Safe to run multiple times."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for plan_data in PLANS:
            slug = plan_data.pop("slug")
            obj, created = SubscriptionPlan.objects.get_or_create(
                slug=slug,
                defaults=plan_data,
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  Created plan: {obj.name}"))
            else:
                # Update fields in case they've drifted (e.g. price changes)
                changed = False
                for field, value in plan_data.items():
                    if str(getattr(obj, field)) != str(value):
                        setattr(obj, field, value)
                        changed = True
                if changed:
                    obj.save()
                    updated_count += 1
                    self.stdout.write(self.style.WARNING(f"  Updated plan:  {obj.name}"))
                else:
                    self.stdout.write(f"  OK (no change): {obj.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone — {created_count} created, {updated_count} updated, "
                f"{len(PLANS) - created_count - updated_count} unchanged."
            )
        )
