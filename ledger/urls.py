from django.urls import path

from ledger.views import GetWalletView, ListLedgerView, TransferToUserView

urlpatterns = [
    path("transfer/", TransferToUserView.as_view(), name="transfer-to-user"),
    path("ledgers/", ListLedgerView.as_view(), name="list-ledger-view"),
    path("me/", GetWalletView.as_view(), name="get-wallet-view"),
]
