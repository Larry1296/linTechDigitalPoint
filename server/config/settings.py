from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import config


BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
# Production: the one public domain (e.g. app.example.co.ke). When set, the hosts, trusted origins, receipt links and
# M-Pesa callback address below default to https://<domain>, so a deployment needs only this one address.
SITE_DOMAIN = config("SITE_DOMAIN", default="").strip().lower()
SITE_URL = f"https://{SITE_DOMAIN}" if SITE_DOMAIN else ""
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default=f"{SITE_DOMAIN},localhost,127.0.0.1" if SITE_DOMAIN else "localhost,127.0.0.1",
    cast=lambda value: [host.strip() for host in value.split(",") if host.strip()],
)
# A frontend served apart from the API (the static site https://dukaflow.co.ke calling https://api.dukaflow.co.ke):
# the only browser origins allowed to call the API with credentials. Empty when the web app and API share one origin
# (deploy/ with Caddy, or the Vite proxy locally), which needs no CORS.
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="",
    cast=lambda value: [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()],
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "x-organization-id", "x-branch-id")
CORS_URLS_REGEX = r"^/(api|media)/.*$"
# Those frontend origins send the forms, so they are trusted for CSRF too, besides the API's own address.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default=",".join(dict.fromkeys([SITE_URL, *CORS_ALLOWED_ORIGINS] if SITE_URL
                                   else ["http://localhost:5173", "http://127.0.0.1:5173", *CORS_ALLOWED_ORIGINS])),
    cast=lambda value: [origin.strip() for origin in value.split(",") if origin.strip()],
)
# Behind the HTTPS proxy (Caddy in deploy/), which ends TLS and tells Django the request was https.
if config("BEHIND_HTTPS_PROXY", default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)  # the proxy already redirects to https
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# APPLICATIONS
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = ["corsheaders", "rest_framework", "drf_spectacular", "django_filters"]
LOCAL_APPS = [
    "apps.tenancy.apps.TenancyConfig",
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.commerce.apps.CommerceConfig",
    "apps.cyber.apps.CyberConfig",
    "apps.mpesa.apps.MpesaConfig",
    "apps.chama.apps.ChamaConfig",
    "apps.hotel.apps.HotelConfig",
    "apps.assistant.apps.AssistantConfig",
    "apps.accounting.apps.AccountingConfig",
    "apps.market.apps.MarketConfig",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # first, so its headers reach every API answer (also errors and preflights)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.session_lock.IdleSessionMiddleware",
    "apps.tenancy.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# URLS
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# TEMPLATES
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# DATABASE
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "ATOMIC_REQUESTS": True,
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        # Reuse connections between requests in production (seconds); checked before use so a restart of the database
        # never hands out a dead one.
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=0, cast=int),
        "CONN_HEALTH_CHECKS": True,
        "TEST": {"NAME": config("DB_TEST_NAME", default="test_lintech_digital_point")},
    }
}

# PASSWORD VALIDATION
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
PASSWORD_RESET_TIMEOUT = 3600

# INTERNATIONALIZATION
LANGUAGE_CODE = "en-ke"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# STATIC / MEDIA
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed copies of the admin's static files, served by WhiteNoise.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DJANGO REST FRAMEWORK
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "apps.tenancy.exceptions.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "2000/hour", "auth": "10/minute", "unlock": "5/minute"},
}
SPECTACULAR_SETTINGS = {"TITLE": config("PLATFORM_NAME", default="DukaFlow") + " API", "VERSION": "1.0.0"}

# CORS / CSRF
FRONTEND_URL = config("FRONTEND_URL", default=SITE_URL or "http://localhost:5173")

# COOKIES / SESSION
COOKIE_SECURE = config("COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "apps.accounts.api.csrf_failure"
CSRF_COOKIE_SAMESITE = "Lax"  # dukaflow.co.ke and api.dukaflow.co.ke are one site, so Lax cookies still reach the API
# The HttpOnly cookie identifies the account after idle access locks.
# Only explicit activity or password unlock renews the shorter access deadline.
SESSION_COOKIE_AGE = config("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 30, cast=int)
SESSION_SAVE_EVERY_REQUEST = False
SESSION_IDLE_TIMEOUT = max(61, config("SESSION_IDLE_TIMEOUT", default=15 * 60, cast=int))
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# LINTECH BUSINESS SETTINGS
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
# SMTP, with EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend (password resets and emailed receipts).
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_TIMEOUT = 20

# LOGGING: everything to the console, where Docker keeps it (docker compose logs app).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
    "loggers": {"django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}

# DARAJA / EXTERNAL INTEGRATIONS
DARAJA_CONSUMER_KEY = config("DARAJA_CONSUMER_KEY", default="")
DARAJA_CONSUMER_SECRET = config("DARAJA_CONSUMER_SECRET", default="")
DARAJA_SHORTCODE = config("DARAJA_SHORTCODE", default="")
DARAJA_PASSKEY = config("DARAJA_PASSKEY", default="")

PLATFORM_NAME = config("PLATFORM_NAME", default="DukaFlow")
PLATFORM_CONTACT_EMAIL = config("PLATFORM_CONTACT_EMAIL", default="")
# Website help assistant (Claude). Without a key the chat endpoint answers 503 and the widget shows contact details.
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
ASSISTANT_MODEL = config("ASSISTANT_MODEL", default="claude-opus-5-5")
# Each business's own assistant in the workspace (answers from that business's records). It can use Claude
# (ANTHROPIC_API_KEY) or OpenAI (OPENAI_API_KEY); owners choose per business, and this is the default.
OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
BUSINESS_ASSISTANT_PROVIDER = config("BUSINESS_ASSISTANT_PROVIDER", default="anthropic")
BUSINESS_ASSISTANT_ANTHROPIC_MODEL = config("BUSINESS_ASSISTANT_ANTHROPIC_MODEL", default="claude-opus-5-5")
# Lets the business assistant (Claude only) search Kenyan online shops to compare the business's prices with the market.
# Each search is billed by Anthropic on top of tokens; set to False to turn it off.
BUSINESS_ASSISTANT_WEB_SEARCH = config("BUSINESS_ASSISTANT_WEB_SEARCH", default=True, cast=bool)
BUSINESS_ASSISTANT_OPENAI_MODEL = config("BUSINESS_ASSISTANT_OPENAI_MODEL", default="gpt-5.5")
BUSINESS_ASSISTANT_EFFORT = config("BUSINESS_ASSISTANT_EFFORT", default="medium")  # low, medium or high
# Looks up money market fund rates (e.g. CIC's) every 10 days with Claude's web search (apps/accounting/fund_rates.py).
FUND_RATE_MODEL = config("FUND_RATE_MODEL", default="claude-opus-5-5")
# Public address of the web app, used in receipt links sent to customers (e.g. https://app.example.com).
PUBLIC_APP_URL = config("PUBLIC_APP_URL", default=SITE_URL)
# Public address of the API, for files it serves itself (business logos on receipts); differs from PUBLIC_APP_URL when
# the web app is a separate static site (https://dukaflow.co.ke with the API at https://api.dukaflow.co.ke).
PUBLIC_API_URL = config("PUBLIC_API_URL", default=SITE_URL)

# API device sessions are separate from Django admin session authentication.
JWT_SIGNING_KEY = config('JWT_SIGNING_KEY', default=SECRET_KEY)
JWT_KEY_ID = config('JWT_KEY_ID', default='primary')
JWT_ISSUER = config('JWT_ISSUER', default='lintech-api')
JWT_AUDIENCE = config('JWT_AUDIENCE', default='lintech-workspace')
JWT_ACCESS_SECONDS = config('JWT_ACCESS_SECONDS', default=180, cast=int)
# The workspace never locks for being idle (there is no idle setting, so no .env can bring one back): it stays open
# for the session's 12 hours, kept alive by refreshing the access token, and locks only when the person locks it.
DEVICE_ABSOLUTE_SECONDS = config('DEVICE_ABSOLUTE_SECONDS', default=43200, cast=int)
REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = ['apps.accounts.device_auth.DeviceJWTAuthentication']
MIDDLEWARE[MIDDLEWARE.index('apps.accounts.session_lock.IdleSessionMiddleware')] = 'apps.accounts.device_auth.DeviceAuthenticationMiddleware'


# Subscription payments by M-Pesa STK push (Safaricom Daraja). MPESA_MODE: off | sandbox | production | simulate.
# "simulate" only works with DEBUG on: payments complete by themselves a few seconds after the prompt, for local testing.
MPESA_MODE = config("MPESA_MODE", default="off")
MPESA_CONSUMER_KEY = config("MPESA_CONSUMER_KEY", default="")
MPESA_CONSUMER_SECRET = config("MPESA_CONSUMER_SECRET", default="")
MPESA_SHORTCODE = config("MPESA_SHORTCODE", default="")
MPESA_PASSKEY = config("MPESA_PASSKEY", default="")
MPESA_TRANSACTION_TYPE = config("MPESA_TRANSACTION_TYPE", default="CustomerPayBillOnline")  # or CustomerBuyGoodsOnline for a till
MPESA_PARTY_B = config("MPESA_PARTY_B", default="")  # the till number when it differs from the shortcode
MPESA_CALLBACK_BASE_URL = config("MPESA_CALLBACK_BASE_URL", default=SITE_URL)  # public https address Safaricom can reach
MPESA_CALLBACK_TOKEN = config("MPESA_CALLBACK_TOKEN", default="")  # long random secret placed in the callback address
# Optional: the addresses Safaricom posts payment notices from. When set, notices from anywhere else are refused (on top of
# the secret in each address). Comma separated, e.g. Safaricom's published callback IPs.
MPESA_CALLBACK_IPS = config("MPESA_CALLBACK_IPS", default="", cast=lambda value: [ip.strip() for ip in value.split(",") if ip.strip()])
# Each business's own Daraja secrets (M-Pesa prompts at the till) are stored encrypted with this Fernet key; when it is
# empty a key derived from SECRET_KEY is used. Changing it makes the stored secrets unreadable (owners re-enter them).
FIELD_ENCRYPTION_KEY = config("FIELD_ENCRYPTION_KEY", default="")
