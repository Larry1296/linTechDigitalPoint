# API

The API root is `/api/v1/`; OpenAPI is `/api/schema/` and Swagger is `/api/docs/`. Authentication provides CSRF, login, logout and current permissions. Public catalog uses a deliberately restricted serializer. Internal locations require authentication and mutation requires Django model permissions. Errors use DRF structured detail responses.

Internal receiving endpoints are under `/api/v1/inventory/`: `POST /receipts/` completes an atomic multi-line receipt, `GET /receipts/` lists history, `GET /receipts/<id>/` shows placements, and `GET /variants/search/` searches active stock variants. These endpoints require staff permissions and are excluded from the public storefront API.

`GET /inventory/categories/available/` returns only categories assigned to active racks, including eligible rack names. Rack configuration accepts a primary category and additional allowed categories. Product variants support flexible option assignments; internal serializers include physical, reserved, available, latest BP, and average stock cost, while public serializers remain restricted.
