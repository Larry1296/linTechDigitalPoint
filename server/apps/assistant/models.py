"""What the platform owner controls about the assistants: the public chat's switch and wording, the help articles
(edited here instead of in code), and the questions visitors asked, so gaps in the articles can be filled.

These belong to the platform, not to any business, so they are ordinary models (no organization).
"""
from django.conf import settings
from django.db import models


class PublicChatSettings(models.Model):
    """One row (pk=1): the public help chat on the website."""
    enabled = models.BooleanField(default=True)
    greeting = models.TextField(blank=True)  # blank: the built-in greeting
    suggestions = models.JSONField(default=list, blank=True)  # suggested questions; empty: the built-in ones
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]


class HelpArticle(models.Model):
    """An article as the platform owner edited it. ``slug`` matches a built-in article's file name to replace it
    (or hide it with ``active=False``); any other slug is a new article. ``body`` holds the ``## Question`` sections."""
    PUBLIC, ADMIN = "PUBLIC", "ADMIN"
    audience = models.CharField(max_length=10, choices=[(PUBLIC, "Public help chat"), (ADMIN, "Platform administrator")])
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=160)
    body = models.TextField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["audience", "slug"], name="assistant_article_audience_slug")]
        ordering = ["audience", "slug"]


class PublicQuestion(models.Model):
    """A question asked in the public chat, and which articles it was answered from (none: a gap to fill).
    Only the question is kept: no IP address, name or the rest of the conversation."""
    question = models.TextField()
    articles = models.JSONField(default=list, blank=True)
    answered = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
