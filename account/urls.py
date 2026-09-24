from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from .views import LoginView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("login/", LoginView.as_view()),
    path("refresh/", TokenRefreshView.as_view()),
    path("logout/", TokenBlacklistView.as_view()),
]
