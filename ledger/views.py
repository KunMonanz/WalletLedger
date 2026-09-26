from rest_framework import generics, permissions


class InitiateTransactionView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
