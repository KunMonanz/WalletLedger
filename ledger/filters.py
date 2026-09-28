import django_filters

from ledger.models import LedgerEntry, Transaction


class LedgerEntryFilter(django_filters.FilterSet):
    direction = django_filters.ChoiceFilter(choices=LedgerEntry.Direction.choices)
    type = django_filters.ChoiceFilter(
        field_name="transaction__type", choices=Transaction.TransactionType.choices
    )
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    min_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="lte")

    class Meta:
        model = LedgerEntry
        fields = [
            "direction",
            "type",
            "created_after",
            "created_before",
            "min_amount",
            "max_amount",
        ]
