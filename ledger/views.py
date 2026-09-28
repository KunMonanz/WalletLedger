import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.throttle import UserThrottle
from ledger.cache_handling import ledgers_cache_key, wallet_cache
from ledger.error import InsufficientFunds, InvalidTransfer
from ledger.filters import LedgerEntryFilter
from ledger.models import FundingIntent, Wallet
from ledger.paystack import PaystackError
from ledger.serializer import (
    FundSerializer,
    LedgerEntrySerialiazer,
    TransferSerializer,
    WalletSerializer,
)

from .services import (
    FundingService,
    LedgerQueryService,
    TransactionCommandService,
    WalletQueryService,
)


class TransferToUserView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransferSerializer
    throttle_classes = [UserThrottle]

    def create(self, request, *args, **kwargs):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"detail": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer()
        serializer.is_valid(raise_exception=True)

        amount_naira = serializer.validated_data["amount"]
        amount = amount_naira * 100
        recipient_id = serializer.validated_data["recipient_wallet_id"]
        sender_id = self.request.user.wallet.id

        try:
            txn = TransactionCommandService().transfer(
                sender_id=sender_id,
                recipient_id=recipient_id,
                amount=amount,
                idempotency_key=idempotency_key,
            )
        except InsufficientFunds as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransfer as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Wallet.DoesNotExist:
            return Response({"detail": "Recipient not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "id": txn.id,
                "status": txn.status,
                "amount": txn.amount,
                "created_at": txn.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class ListLedgerView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LedgerEntrySerialiazer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LedgerEntryFilter

    def get_queryset(self):
        wallet = self.request.user.wallet
        return LedgerQueryService.get_ledger_of_wallet(wallet)

    def list(self, request, *args, **kwargs):
        current_user_wallet_id = request.user.wallet.id
        cache_key = ledgers_cache_key(current_user_wallet_id)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data, status=status.HTTP_200_OK)
        response = super().list(request, *args, **kwargs)
        cache.set(key=cache_key, value=response.data, timeout=300)
        return response


class GetWalletView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WalletSerializer

    def retrieve(self, request, *args, **kwargs):
        current_user_wallet_id = request.user.wallet.id
        cache_key = wallet_cache(current_user_wallet_id)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)
        wallet = WalletQueryService.get_wallet_by_id(current_user_wallet_id)
        serializer = self.get_serializer_class()
        cache.set(key=cache_key, value=serializer(wallet).data, timeout=300)
        return Response(serializer(wallet).data)


class FundWalletView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserThrottle]

    def post(self, request):
        serializer = FundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = int(serializer.validated_data["amount"] * 100)
        try:
            url = FundingService.initiate_funding(request.user, amount)
        except PaystackError:
            return Response(
                {"detail": "Payment provider error."}, status=status.HTTP_502_BAD_GATEWAY
            )
        return Response({"authorization_url": url}, status=status.HTTP_201_CREATED)


class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def post(self, request):
        signature = request.headers.get("x-paystack-signature", "")
        expected = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(), request.body, hashlib.sha512
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return Response(status=401)

        payload = json.loads(request.body)
        if payload.get("event") == "charge.success":
            data = payload["data"]
            try:
                FundingService().complete_funding(
                    data["reference"], data["amount"], data["currency"]
                )
            except FundingIntent.DoesNotExist:
                logging.getLogger(__name__).warning("Unknown reference %s", data["reference"])
        return Response(status=200)
