from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView

from config.throttle import (
    CombinedThrottle,
    EmailThrottle,
    GlobalThrottle,
    IpThrottle,
    UserThrottle,
)

from .serializers import RegisterSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [GlobalThrottle, UserThrottle, EmailThrottle, IpThrottle, CombinedThrottle]


class LoginView(TokenObtainPairView):
    throttle_classes = [GlobalThrottle, UserThrottle, EmailThrottle, IpThrottle, CombinedThrottle]
    permission_classes = [AllowAny]
