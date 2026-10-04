from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def device_security_checks(app_configs, **kwargs):
    errors=[]
    if settings.JWT_SIGNING_KEY == settings.SECRET_KEY or len(settings.JWT_SIGNING_KEY.encode()) < 32:
        errors.append(Error('Configure an independent JWT_SIGNING_KEY of at least 32 random bytes.',id='accounts.E001'))
    if not settings.COOKIE_SECURE:
        errors.append(Error('Production refresh and CSRF cookies require COOKIE_SECURE=True and HTTPS.',id='accounts.E002'))
    return errors
