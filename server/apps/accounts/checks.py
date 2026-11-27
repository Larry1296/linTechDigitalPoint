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


@register(Tags.compatibility)
def email_sending_check(app_configs, **kwargs):
    """A live server must send email: password resets and emailed receipts depend on it. Without these settings
    Django only writes each email to the log, and the person waits for a message that never comes."""
    from django.core.checks import Warning
    if settings.DEBUG:
        return []
    warnings = []
    if settings.EMAIL_BACKEND.endswith((".console.EmailBackend", ".dummy.EmailBackend", ".locmem.EmailBackend")):
        warnings.append(Warning("Email is not being sent: EMAIL_BACKEND writes messages to the log. Set EMAIL_BACKEND="
                                "django.core.mail.backends.smtp.EmailBackend with EMAIL_HOST, EMAIL_HOST_USER and "
                                "EMAIL_HOST_PASSWORD.", id="accounts.W001"))
    elif settings.DEFAULT_FROM_EMAIL.endswith("@localhost") or "localhost" in settings.DEFAULT_FROM_EMAIL:
        warnings.append(Warning("DEFAULT_FROM_EMAIL is not a real sender address; mail providers refuse it. Set it to a "
                                "verified address, e.g. DukaFlow <noreply@dukaflow.co.ke>.", id="accounts.W002"))
    return warnings
