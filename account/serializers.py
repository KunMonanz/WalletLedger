from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")
        read_only_fields = ("id",)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
