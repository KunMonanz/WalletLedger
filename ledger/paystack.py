import requests
from django.conf import settings
from rest_framework import status

BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    pass


def initialize_payment(email: str, amount: int, reference: str) -> str:
    response = requests.post(
        f"{BASE_URL}/transaction/initialize",
        json={"email": email, "amount": amount, "reference": reference, "currency": "NGN"},
        headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
        timeout=10,
    )
    body = response.json()
    if response.status_code != status.HTTP_200_OK or not body.get("status"):
        raise PaystackError(body.get("message", "Paystack initialize failed"))
    return body["data"]["authorization_url"]
