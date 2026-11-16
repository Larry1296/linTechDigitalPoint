from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler, set_rollback

def exception_handler(exc, context):
    if isinstance(exc, (ObjectDoesNotExist, DjangoValidationError, IntegrityError)):
        set_rollback()
    if isinstance(exc, ObjectDoesNotExist):
        return Response({"detail": "Record not found in this business."}, status=404)
    if isinstance(exc, DjangoValidationError):
        return Response(getattr(exc, "message_dict", {"detail": exc.messages}), status=400)
    if isinstance(exc, IntegrityError):
        # Never disclose another tenant's IDs, references, or constraint details.
        return Response({"detail": "The operation conflicts with an existing record or business relationship."}, status=400)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response
    return _server_error(exc, context)


def _organization_id(request):
    """The business the request was working in: its scope while the view ran, else the one its session chose."""
    from .context import organization_id
    return organization_id() or getattr(getattr(request, "organization", None), "pk", None)


def _server_error(exc, context):
    """A crash nobody planned for. Nothing is saved (the request's changes roll back); the person gets a plain message
    with a reference, and the details are kept for the platform owner: in the server log, and (by ServerErrorLog
    below, once the request's transaction is over) as a SERVER_ERROR entry in the business's audit log."""
    import logging
    import traceback
    import uuid
    set_rollback()
    reference = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    request = context.get("request")
    logging.getLogger("apps.errors").error("%s %s %s", reference, getattr(request, "method", ""), getattr(request, "path", ""), exc_info=exc)
    raw = getattr(request, "_request", None)
    if raw is not None:
        raw._server_error = {"reference": reference, "method": request.method, "path": request.path,
                             "organization": _organization_id(request),
                             "user": getattr(getattr(request, "user", None), "pk", None),
                             "error": f"{type(exc).__name__}: {exc}"[:500],
                             "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-6000:]}
    return Response({"detail": f"Something went wrong on the server and nothing was saved. Try again; if it happens again, "
                               f"tell support the reference {reference}.", "reference": reference}, status=500)


class ServerErrorLog:
    """Keeps a crash's details (see _server_error) in the business's audit log, after the request's own transaction has
    rolled back, so the record stays."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        error = getattr(request, "_server_error", None)
        if error:
            try:
                from apps.core.models import AuditLog
                from apps.tenancy.models import Organization
                from .context import organization_context
                organization = Organization.objects.filter(pk=error["organization"]).first() if error["organization"] else None
                with organization_context(organization):
                    AuditLog.objects.create(action="SERVER_ERROR", object_type=error["path"][:80], object_id=error["reference"],
                                            user_id=error["user"], after=error)
            except Exception:  # noqa: BLE001 - keeping the record must never break the answer
                import logging
                logging.getLogger("apps.errors").exception("Could not keep %s", error.get("reference"))
        return response
