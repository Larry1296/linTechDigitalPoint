from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import HasLinTechPermission
from .api import _receipt_data
from .receipt_corrections import correct_receipt_line


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def receipt_line_correct(request, pk, line_id):
    line = correct_receipt_line(receipt_id=pk, line_id=line_id, user=request.user, data=request.data)
    return Response(_receipt_data(line.receipt))
