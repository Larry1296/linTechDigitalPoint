import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR=Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent/".env")
SECRET_KEY=os.getenv("DJANGO_SECRET_KEY","development-only-change-me")
DEBUG=os.getenv("DJANGO_DEBUG","true").lower()=="true"
ALLOWED_HOSTS=os.getenv("ALLOWED_HOSTS","localhost,127.0.0.1").split(",")
INSTALLED_APPS=["django.contrib.admin","django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","rest_framework","drf_spectacular","django_filters","core","catalog","inventory","commerce"]
MIDDLEWARE=["django.middleware.security.SecurityMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware","django.contrib.messages.middleware.MessageMiddleware","django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF="config.urls"
TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request","django.contrib.auth.context_processors.auth","django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION="config.wsgi.application"
DATABASES={"default":{"ENGINE":"django.db.backends.postgresql","NAME":os.getenv("POSTGRES_DB","lintech_digital_point"),"USER":os.getenv("POSTGRES_USER",os.getenv("USER","lintech")),"PASSWORD":os.getenv("POSTGRES_PASSWORD",""),"HOST":os.getenv("POSTGRES_HOST","/var/run/postgresql"),"PORT":os.getenv("POSTGRES_PORT","5432"),"TEST":{"NAME":os.getenv("POSTGRES_TEST_DB","test_lintech_digital_point")}}}
AUTH_PASSWORD_VALIDATORS=[{"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator"},{"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"}]
LANGUAGE_CODE="en-ke"; TIME_ZONE="Africa/Nairobi"; USE_I18N=True; USE_TZ=True
STATIC_URL="static/"; STATIC_ROOT=BASE_DIR/"staticfiles"; DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"
REST_FRAMEWORK={"DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],"DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"],"DEFAULT_SCHEMA_CLASS":"drf_spectacular.openapi.AutoSchema","DEFAULT_THROTTLE_CLASSES":["rest_framework.throttling.AnonRateThrottle","rest_framework.throttling.UserRateThrottle"],"DEFAULT_THROTTLE_RATES":{"anon":"100/hour","user":"2000/hour","auth":"10/minute"}}
SPECTACULAR_SETTINGS={"TITLE":"LinTech Digital Point API","VERSION":"1.0.0"}
CSRF_COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true"; SESSION_COOKIE_SECURE=CSRF_COOKIE_SECURE; SESSION_COOKIE_HTTPONLY=True; SESSION_COOKIE_SAMESITE="Lax"

