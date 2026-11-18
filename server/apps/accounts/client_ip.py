"""The visitor's own address, for rate limits. Behind Cloudflare and the host's proxy every request reaches the app from
the proxy's address, so without this all signed-out visitors shared one allowance (100 an hour) and, once it ran out,
nobody could fetch a security token or sign in. Cloudflare puts the visitor's address in CF-Connecting-IP."""
from django.conf import settings


class ClientAddressMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = getattr(settings, "CLIENT_IP_HEADER", "")
        address = request.META.get(header, "").strip() if header else ""
        if address:
            request.META["REMOTE_ADDR"] = address
        return self.get_response(request)
