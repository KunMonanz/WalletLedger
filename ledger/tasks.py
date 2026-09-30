import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from ledger import paystack
from ledger.models import FundingIntent
from ledger.services import FundingService

logger = logging.getLogger(__name__)


@shared_task
def reconcile_pending_fundings():
    cutoff = timezone.now() - timedelta(minutes=10)
    unreconciled_fundings = FundingIntent.objects.filter(
        status=FundingIntent.Status.PENDING,
        created_at__lt=cutoff,
    )
    for intent in unreconciled_fundings:
        try:
            data = paystack.verify_payment(intent.reference)
        except paystack.PaystackError:
            logger.warning("Verify failed for %s, will retry next run", intent.reference)
            continue

        if data["status"] == "success":
            FundingService().complete_funding(intent.reference, data["amount"], data["currency"])
            logger.info("Reconciled funding %s as successful", intent.reference)
        elif data["status"] in ("failed", "abandoned"):
            FundingService().fail_funding(intent.reference)
            logger.info("Reconciled funding %s as failed", intent.reference)
