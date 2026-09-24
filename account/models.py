import uuid6
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    email = models.EmailField(unique=True)


class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
