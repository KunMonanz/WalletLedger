import hashlib
import logging
import uuid

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from ledger import paystack
from ledger.cache_handling import bump_ledger_version, ledgers_cache_key, wallet_cache
from ledger.error import InsufficientFunds, InvalidTransfer
from ledger.models import FundingIntent, LedgerEntry, Transaction, Wallet

logger = logging.getLogger(__name__)


class TransactionCommandService:
    def __init__(self) -> None:
        self.wallet_command_service = WalletCommandService
        self.ledger_command_service = LedgerCommandService

    @staticmethod
    def _create_transaction_entry(
        transaction_type: str, idempotency_key: str, amount: int, recipient_id, sender_id
    ):
        request_fingerprint = _fingerprint(
            sender_id=sender_id, recipient_id=recipient_id, amount=amount
        )
        transaction = Transaction.objects.create(
            type=transaction_type,
            idempotency_key=idempotency_key,
            amount=amount,
            request_fingerprint=request_fingerprint,
        )
        return transaction

    def transfer(self, sender_id, recipient_id, amount, idempotency_key):
        if amount <= 0:
            raise InvalidTransfer("Amount must be positive and greater than 0")
        if sender_id == recipient_id:
            raise InvalidTransfer("Cannot transfer to the same wallet")
        existing = TransactionQueryService.transaction_exists(idempotency_key)
        if existing:
            if existing.request_fingerprint != _fingerprint(sender_id, recipient_id, amount):
                raise InvalidTransfer("Idempotency key reused with different parameters")
            return existing

        try:
            with transaction.atomic():
                return self._post_transfer(
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    amount=amount,
                    idempotency_key=idempotency_key,
                )
        except IntegrityError:
            existing = TransactionQueryService.transaction_exists(idempotency_key)
            if existing:
                return existing
            raise

    def _post_transfer(self, sender_id, recipient_id, amount, idempotency_key):
        wallets = WalletCommandService._lock_wallets_for_update(sender_id, recipient_id)
        if len(wallets) != 2:
            raise Wallet.DoesNotExist("Sender or recipient not found")
        sender, recipient = wallets[sender_id], wallets[recipient_id]

        if sender.type == Wallet.WalletType.USER and sender.balance < amount:
            raise InsufficientFunds("Insufficient balance")

        txn = TransactionCommandService._create_transaction_entry(
            transaction_type=Transaction.TransactionType.TRANSFER,
            amount=amount,
            idempotency_key=idempotency_key,
            recipient_id=recipient_id,
            sender_id=sender_id,
        )

        LedgerEntry.objects.bulk_create(
            [
                self.ledger_command_service(sender)._create_debit_ledger_entry(
                    txn=txn, amount=amount
                ),
                self.ledger_command_service(recipient)._create_credit_ledger_entry(
                    txn=txn, amount=amount
                ),
            ]
        )

        self.wallet_command_service(sender)._debit_wallet(amount=amount)
        self.wallet_command_service(recipient)._credit_wallet(amount=amount)

        txn = self._mark_transaction_successful(txn)

        def _invalidate():
            cache.delete(wallet_cache(sender.id))
            cache.delete(wallet_cache(recipient.id))
            bump_ledger_version(sender.id)
            bump_ledger_version(recipient.id)

        transaction.on_commit(_invalidate)
        return txn

    def _mark_transaction_successful(self, txn: Transaction):
        txn.status = Transaction.Status.SUCCESSFUL
        txn.save(update_fields=["status", "updated_at"])
        return txn


class TransactionQueryService:
    @staticmethod
    def transaction_exists(idempotency_key: str):
        return Transaction.objects.filter(idempotency_key=idempotency_key).first()


class WalletQueryService:
    @staticmethod
    def get_wallet_by_id(wallet_id: str) -> Wallet | None:
        return Wallet.objects.get(id=wallet_id)


class WalletCommandService:
    def __init__(self, wallet: Wallet):
        self.wallet = wallet

    @staticmethod
    def _lock_wallets_for_update(sender_id, recipient_id) -> dict[uuid.UUID, Wallet]:
        return {
            wallet.id: wallet
            for wallet in Wallet.objects.select_for_update()
            .filter(id__in=[sender_id, recipient_id])
            .order_by("id")
        }

    def _credit_wallet(self, amount: int):
        self.wallet.balance += amount
        self.wallet.save(update_fields=["balance", "updated_at"])
        return self.wallet

    def _debit_wallet(self, amount: int):
        self.wallet.balance -= amount
        self.wallet.save(update_fields=["balance", "updated_at"])
        return self.wallet


class LedgerCommandService:
    def __init__(self, wallet: Wallet) -> None:
        self.wallet = wallet
        self.wallet_command_service = WalletCommandService
        self.transaction_command_service = TransactionCommandService
        self.wallet_query_service = WalletQueryService

    def _create_debit_ledger_entry(self, amount: int, txn: Transaction):
        return LedgerEntry(
            transaction=txn,
            wallet=self.wallet,
            amount=amount,
            direction=LedgerEntry.Direction.DEBIT,
        )

    def _create_credit_ledger_entry(self, amount: int, txn: Transaction):
        return LedgerEntry(
            transaction=txn,
            wallet=self.wallet,
            amount=amount,
            direction=LedgerEntry.Direction.CREDIT,
        )


class LedgerQueryService:
    @staticmethod
    def get_ledger_of_wallet(wallet: Wallet) -> QuerySet[LedgerEntry]:
        return LedgerEntry.objects.filter(wallet=wallet).order_by("-created_at")


def _fingerprint(sender_id, recipient_id, amount):
    raw = f"{sender_id}:{recipient_id}:{amount}"
    return hashlib.sha256(raw.encode()).hexdigest()


class FundingService:
    @staticmethod
    def initiate_funding(user, amount: int) -> str:
        reference = f"fund_{uuid.uuid4().hex}"
        FundingIntent.objects.create(reference=reference, wallet=user.wallet, amount=amount)
        return paystack.initialize_payment(user.email, amount, reference)

    def complete_funding(self, reference: str, paid_amount: int, currency: str) -> None:
        with transaction.atomic():
            intent = FundingIntent.objects.select_for_update().get(reference=reference)
            if intent.status == FundingIntent.Status.SUCCESSFUL:
                return

            if paid_amount != intent.amount or currency != "NGN":
                logger.error("Funding mismatch for %s", reference)
                return

            clearing_id = Wallet.objects.only("id").get(name="paystack_clearing").id
            wallets = WalletCommandService._lock_wallets_for_update(
                sender_id=clearing_id, recipient_id=intent.wallet_id
            )
            clearing, user_wallet = wallets[clearing_id], wallets[intent.wallet_id]
            txn = TransactionCommandService._create_transaction_entry(
                transaction_type=Transaction.TransactionType.FUNDING,
                amount=intent.amount,
                idempotency_key=f"paystack:{reference}",
                sender_id=clearing_id,
                recipient_id=intent.wallet_id,
            )

            LedgerEntry.objects.bulk_create(
                [
                    LedgerCommandService(clearing)._create_debit_ledger_entry(
                        txn=txn, amount=intent.amount
                    ),
                    LedgerCommandService(user_wallet)._create_credit_ledger_entry(
                        txn=txn, amount=intent.amount
                    ),
                ]
            )
            WalletCommandService(clearing)._debit_wallet(intent.amount)
            WalletCommandService(user_wallet)._credit_wallet(intent.amount)

            TransactionCommandService()._mark_transaction_successful(txn)
            self._mark_funding_intent_successful(intent)

            def _invalidate():
                cache.delete(wallet_cache(clearing.id))
                cache.delete(wallet_cache(user_wallet.id))
                bump_ledger_version(clearing.id)
                bump_ledger_version(user_wallet.id)

            transaction.on_commit(_invalidate)

    def _mark_funding_intent_successful(self, funding_intent: FundingIntent):
        funding_intent.status = FundingIntent.Status.SUCCESSFUL
        funding_intent.save(update_fields=["status"])
