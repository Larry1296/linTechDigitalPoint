from pathlib import Path

from decouple import config


BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=lambda value: [host.strip() for host in value.split(",") if host.strip()],
)
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:5173,http://127.0.0.1:5173",
    cast=lambda value: [origin.strip() for origin in value.split(",") if origin.strip()],
)

# APPLICATIONS
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = ["rest_framework", "drf_spectacular", "django_filters"]
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
    "apps.assistant.apps.AssistantConfig",
    "apps.accounting.apps.AccountingConfig",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE
MIDDLEWARE = [
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
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173")

# COOKIES / SESSION
COOKIE_SECURE = config("COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# The HttpOnly cookie identifies the account after idle access locks.
# Only explicit activity or password unlock renews the shorter access deadline.
SESSION_COOKIE_AGE = config("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 30, cast=int)
SESSION_SAVE_EVERY_REQUEST = False
SESSION_IDLE_TIMEOUT = max(61, config("SESSION_IDLE_TIMEOUT", default=15 * 60, cast=int))
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# LINTECH BUSINESS SETTINGS
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="webmaster@localhost")

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
# Public address of the web app, used in receipt links sent to customers (e.g. https://app.example.com).
PUBLIC_APP_URL = config("PUBLIC_APP_URL", default="")

# API device sessions are separate from Django admin session authentication.
JWT_SIGNING_KEY = config('JWT_SIGNING_KEY', default=SECRET_KEY)
JWT_KEY_ID = config('JWT_KEY_ID', default='primary')
JWT_ISSUER = config('JWT_ISSUER', default='lintech-api')
JWT_AUDIENCE = config('JWT_AUDIENCE', default='lintech-workspace')
JWT_ACCESS_SECONDS = config('JWT_ACCESS_SECONDS', default=180, cast=int)
DEVICE_IDLE_SECONDS = config('DEVICE_IDLE_SECONDS', default=15 * 60, cast=int)
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
MPESA_CALLBACK_BASE_URL = config("MPESA_CALLBACK_BASE_URL", default="")  # public https address Safaricom can reach
MPESA_CALLBACK_TOKEN = config("MPESA_CALLBACK_TOKEN", default="")  # long random secret placed in the callback address
