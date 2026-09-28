import hashlib
import hmac
import json
import os
import sys

import requests

reference, amount = sys.argv[1], int(sys.argv[2])
body = json.dumps(
    {
        "event": "charge.success",
        "data": {"reference": reference, "amount": amount, "currency": "NGN", "status": "success"},
    }
).encode()
signature = hmac.new(os.environ["PAYSTACK_SECRET_KEY"].encode(), body, hashlib.sha512).hexdigest()

r = requests.post(
    "http://127.0.0.1:8000/api/wallet/paystack/webhook/",
    data=body,
    headers={"x-paystack-signature": signature, "Content-Type": "application/json"},
)
print(r.status_code)
