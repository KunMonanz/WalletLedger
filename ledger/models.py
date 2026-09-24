import uuid6
from django.conf import settings
from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    class WalletType(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=10, choices=WalletType.choices, default=WalletType.USER)
    name = models.CharField(max_length=50, unique=True, null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    balance = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(type="system") | Q(balance__gte=0),
                name="user_wallet_balance_non_negative",
            ),
            models.CheckConstraint(
                condition=(Q(type="user", user__isnull=False))
                | (Q(type="system", user__isnull=True)),
                name="wallet_user_matches_type",
            ),
        ]


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        FUNDING = "funding", "Funding"
        TRANSFER = "transfer", "Transfer"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESSFUL = "successful", "Successful"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    type = models.CharField(max_length=20, choices=TransactionType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.PositiveBigIntegerField()  # kobo
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LedgerEntry(models.Model):
    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="entries")
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    direction = models.CharField(max_length=6, choices=Direction.choices, db_index=True)
    amount = models.PositiveBigIntegerField()  # kobo
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ledger_entry_amount_positive"),
        ]
        indexes = [models.Index(fields=["wallet", "created_at"])]
