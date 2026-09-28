from rest_framework import serializers
from rest_framework.validators import ValidationError

from ledger.models import LedgerEntry, Wallet


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "type", "status", "amount", "idempotency_key", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "idempotency_key", "created_at", "updated_at"]


class TransferSerializer(serializers.Serializer):
    amount = serializers.BigIntegerField(min_value=100)
    recipient_wallet_id = serializers.UUIDField()

    def validate(self, attrs):
        amount = attrs.get("amount")
        if amount < 100:
            raise ValidationError(detail="Amount cannot be less than 100 NGN")

        return attrs


class LedgerEntrySerialiazer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "direction", "amount", "created_at"]
        read_only_fields = ["id", "direction", "amount", "created_at"]


class WalletSerializer(serializers.ModelSerializer):
    balance_in_naira = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            "id",
            "user",
            "type",
            "name",
            "currency",
            "balance_in_naira",
            "balance",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "type",
            "name",
            "currency",
            "balance",
            "balance_in_naira",
            "created_at",
            "updated_at",
        ]

    def get_balance_in_naira(self, obj: Wallet) -> int:
        return obj.balance / 100


class FundSerializer(serializers.Serializer):
    amount = serializers.BigIntegerField(min_value=100)

    def validate(self, attrs):
        amount = attrs.get("amount")
        if amount < 100:
            raise ValidationError(detail="Amount cannot be less than 100 NGN")

        return attrs
