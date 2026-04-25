"""
Management command: backfill_contribution_transactions

Iterates every unique (church, date, contribution_type) combination that
exists in the Contribution table and calls _sync_contribution_transaction
for each one.  Run this once after deploying the Contribution→Transaction
auto-sync feature so that historical contributions appear on the
Transactions page.

Usage:
    python manage.py backfill_contribution_transactions
    python manage.py backfill_contribution_transactions --dry-run
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum
from decimal import Decimal

from church_finances.models import Contribution, Transaction, Church
from church_finances.views import CONTRIBUTION_CATEGORY_MAP, _CATEGORY_TO_CONTRIB_TYPES


class Command(BaseCommand):
    help = "Backfill Transaction rows from existing Contribution records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created/updated without touching the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Collect all unique (church_id, date, contribution_type) combos
        combos = (
            Contribution.objects
            .values("church_id", "date", "contribution_type")
            .distinct()
        )

        created_count = 0
        updated_count = 0
        skipped = set()  # categories already processed for a (church, date) pair

        for combo in combos:
            church_id = combo["church_id"]
            date = combo["date"]
            contrib_type = combo["contribution_type"]

            category = CONTRIBUTION_CATEGORY_MAP.get(contrib_type)
            if not category:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping unknown contribution_type={contrib_type!r}"
                    )
                )
                continue

            key = (church_id, date, category)
            if key in skipped:
                # Already processed this category for this church+date
                continue
            skipped.add(key)

            contrib_types = _CATEGORY_TO_CONTRIB_TYPES[category]
            total = (
                Contribution.objects
                .filter(church_id=church_id, date=date, contribution_type__in=contrib_types)
                .aggregate(total=Sum("amount"))["total"]
            ) or Decimal("0.00")

            if total <= 0:
                continue

            try:
                church = Church.objects.get(pk=church_id)
            except Church.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  Church {church_id} not found – skipping."))
                continue

            description = f"Contributions – {category.replace('_', ' ').title()}"

            existing = Transaction.objects.filter(
                church=church, date=date, category=category, type="income"
            ).first()

            if dry_run:
                if existing:
                    self.stdout.write(
                        f"  [DRY-RUN] Would UPDATE transaction pk={existing.pk} "
                        f"church={church} date={date} category={category} amount={total}"
                    )
                else:
                    self.stdout.write(
                        f"  [DRY-RUN] Would CREATE transaction "
                        f"church={church} date={date} category={category} amount={total}"
                    )
                continue

            if existing:
                existing.amount = total
                existing.save(update_fields=["amount", "updated_at"])
                updated_count += 1
                self.stdout.write(f"  Updated  pk={existing.pk} {date} {category} → ${total}")
            else:
                Transaction.objects.create(
                    church=church,
                    date=date,
                    category=category,
                    type="income",
                    amount=total,
                    description=description,
                )
                created_count += 1
                self.stdout.write(f"  Created  {date} {category} → ${total}")

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. Created {created_count}, updated {updated_count} transaction(s)."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nDry-run complete – no changes made."))
