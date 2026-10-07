"""Checks the AI keys and models the assistants use, without spending tokens.

    python manage.py check_assistants

For each provider with a key it asks the API about the configured model (a free metadata call), so a wrong key,
a mistyped model or a blocked network shows up here rather than as an error in the chat.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.assistant import business_chat


class Command(BaseCommand):
    help = "Check that the AI assistants' keys and models work."

    def handle(self, *args, **options):
        problems = 0
        checks = [("anthropic", "Public help chat", settings.ASSISTANT_MODEL),
                  ("anthropic", "Business assistant (Claude)", settings.BUSINESS_ASSISTANT_ANTHROPIC_MODEL),
                  ("openai", "Business assistant (ChatGPT)", settings.BUSINESS_ASSISTANT_OPENAI_MODEL)]
        for provider, label, model in checks:
            if not business_chat.configured(provider):
                optional = provider == "openai"
                self.stdout.write((self.style.WARNING if optional else self.style.ERROR)(
                    f"{label}: no {'OPENAI' if optional else 'ANTHROPIC'}_API_KEY set{' (optional)' if optional else ''}."))
                problems += not optional
                continue
            try:
                if provider == "anthropic":
                    business_chat._anthropic().models.retrieve(model)
                else:
                    business_chat._openai().models.retrieve(model)
            except Exception as exc:  # report every failure the same way: this is a diagnostic
                problems += 1
                self.stdout.write(self.style.ERROR(f"{label}: {model} failed: {type(exc).__name__}: {exc}"))
                continue
            self.stdout.write(self.style.SUCCESS(f"{label}: {model} OK"))
        default = business_chat.PROVIDERS.get(settings.BUSINESS_ASSISTANT_PROVIDER, settings.BUSINESS_ASSISTANT_PROVIDER)
        self.stdout.write(f"Business assistants default to {default}; owners can switch on their assistant settings.")
        if problems:
            raise SystemExit(1)
