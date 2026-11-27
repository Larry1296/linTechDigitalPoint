"""One email address belongs to one account. A password reset sends a link to every account with the address, so a
shared or mistyped address would let whoever reads that inbox take over someone else's account (an employee's,
typed wrongly by the owner). Owners, employees and customers all keep their own address, checked here."""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

IN_USE = "This email is already used by another account. Each person needs their own email address."


def clean_email(value, user=None):
    """The address, trimmed; blank stays blank. Raises ValidationError if it is not an email address or another
    account already has it (``user`` is the account it is for, which may keep its own address)."""
    email = (value or "").strip()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError("Enter a valid email address.")
    others = User.objects.filter(email__iexact=email)
    if user is not None and user.pk:
        others = others.exclude(pk=user.pk)
    if others.exists():
        raise ValidationError(IN_USE)
    return email


def reset_form_class():
    """Django's reset form logs a mail server failure and carries on, so the person is told the email was sent when
    it was not. This one lets the failure through, for the page to say so."""
    from django.contrib.auth.forms import PasswordResetForm
    from django.core.mail import EmailMultiAlternatives
    from django.template import loader

    class ResetForm(PasswordResetForm):
        def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
            subject = "".join(loader.render_to_string(subject_template_name, context).splitlines())
            EmailMultiAlternatives(subject, loader.render_to_string(email_template_name, context), from_email, [to_email]).send()

    return ResetForm
