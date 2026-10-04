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
    return drf_exception_handler(exc, context)
