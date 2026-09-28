from rest_framework.throttling import SimpleRateThrottle


class GlobalThrottle(SimpleRateThrottle):
    scope = "global"

    def get_cache_key(self, request, view):
        return "throttle_global"


class UserThrottle(SimpleRateThrottle):
    scope = "user"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle_user_{request.user.pk}"
        return None


class EmailThrottle(SimpleRateThrottle):
    scope = "email"

    def get_cache_key(self, request, view):
        email = request.data.get("email") or request.query_params.get("email")
        if email:
            return f"throttle_email_{email.strip().lower()}"
        return None


class IpThrottle(SimpleRateThrottle):
    scope = "ip"

    def get_cache_key(self, request, view):
        return f"throttle_ip_{self.get_ident(request)}"


class CombinedThrottle(SimpleRateThrottle):
    scope = "combined"

    def get_cache_key(self, request, view):
        ip = self.get_ident(request)
        user_id = request.user.pk if request.user and request.user.is_authenticated else "anon"

        return f"throttle_combined_{ip}_{user_id}"
