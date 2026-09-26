from rest_framework import serializers


class TransacttionSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "type", "status", "amount", "idempotency_key", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "idempotency_key", "created_at", "updated_at"]
