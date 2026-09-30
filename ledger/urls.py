from django.urls import path

from ledger.views import (
    FundWalletView,
    GetWalletView,
    ListLedgerView,
    PaystackWebhookView,
    TransferToUserView,
    VerifyFundingView,
)

urlpatterns = [
    path("transfer/", TransferToUserView.as_view(), name="transfer-to-user"),
    path("ledgers/", ListLedgerView.as_view(), name="list-ledger-view"),
    path("me/", GetWalletView.as_view(), name="get-wallet-view"),
    path("fund/", FundWalletView.as_view(), name="fund-wallet"),
    path("paystack/webhook/", PaystackWebhookView.as_view(), name="paystack-webhook"),
    path("fund/<str:reference>/verify/", VerifyFundingView.as_view(), name="verify-funding"),
]
