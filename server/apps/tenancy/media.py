from django.http import FileResponse, Http404
from apps.catalog.models import ProductImage
from .permissions import membership_for

def private_media(request, path):
    if not membership_for(request.user):
        raise Http404
    image = ProductImage.objects.filter(file=path).first()
    if not image or not image.file:
        raise Http404
    try:
        response = FileResponse(image.file.open('rb'))
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    return response
