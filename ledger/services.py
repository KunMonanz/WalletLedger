from django.db import IntegrityError, transaction

from ledger.error import InsufficientFunds, InvalidTransfer
from ledger.models import LedgerEntry, Transaction, Wallet


class TransctionCommandService:
    def __init__(self) -> None:
        self.wallet_command_service = WalletCommandService
        self.ledger_command_service = LedgerCommandService

    @staticmethod
    def _create_transaction_entry(transaction_type: str, idempotency_key: str, amount: int):
        transaction = Transaction.objects.create(
            type=transaction_type, idempotency_key=idempotency_key, amount=amount
        )
        return transaction

    def transfer(self, sender_id, recipient_id, amount, idempotency_key):
        if amount <= 0:
            raise InvalidTransfer("Amount must be positive and greater than 0")
        if sender_id == recipient_id:
            raise InvalidTransfer("Cannot transfer to the same wallet")
        existing = TransactionQueryService.transaction_exists(idempotency_key)
        if existing:
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
        wallets = self.wallet_command_service._lock_wallets_for_update(sender_id, recipient_id)
        if len(wallets) != 2:
            raise Wallet.DoesNotExist("Sender or recipient not found")
        sender, recipient = wallets[sender_id], wallets[recipient_id]

        if sender.tye == Wallet.WalletType.USER and sender.balance < amount:
            raise InsufficientFunds("Insufficient balance")

        txn = TransctionCommandService._create_transaction_entry(
            transaction_type=Transaction.TransactionType.TRANSFER,
            amount=amount,
            idempotency_key=idempotency_key,
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

        self.wallet_command_service(sender).debit_wallet(amount=amount)
        self.wallet_command_service(recipient).credit_wallet(amount=amount)

        txn = self._mark_transaction_successful(txn)
        return txn

    def _mark_transaction_successful(self, txn: Transaction):
        txn.status = Transaction.Status.SUCCESSFUL
        txn.save(update_fields=["status", "updated_at"])
        return txn


class TransactionQueryService:
    def __init__(self) -> None:
        self.transaction_query_service = TransactionQueryService

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
    def _lock_wallets_for_update(sender_id, recipient_id):
        return {
            wallet.id: wallet
            for wallet in Wallet.objects.select_for_update()
            .filter(id__in=[sender_id, recipient_id])
            .order_by("id")
        }

    def credit_wallet(self, amount: int):
        self.wallet.balance += amount
        self.wallet.save()
        return self.wallet

    def debit_wallet(self, amount: int):
        self.wallet.balance -= amount
        self.wallet.save(update_fields=["balance", "updated_at"])
        return self.wallet


class LedgerCommandService:
    def __init__(self, wallet: Wallet) -> None:
        self.wallet = wallet
        self.wallet_caommand_service = WalletCommandService
        self.transaction_command_service = TransctionCommandService
        self.wallet_query_service = WalletQueryService

    def _create_debit_ledger_entry(self, amount: int, txn: Transaction):
        return LedgerEntry.objects.create(
            transaction=txn,
            wallet=self.wallet,
            amount=amount,
            direction=LedgerEntry.Direction.DEBIT,
        )

    def _create_credit_ledger_entry(self, amount: int, txn: Transaction):
        return LedgerEntry.objects.create(
            transaction=txn,
            wallet=self.wallet,
            amount=amount,
            direction=LedgerEntry.Direction.CREDIT,
        )
