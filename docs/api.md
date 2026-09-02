# API

The API root is `/api/v1/`; OpenAPI is `/api/schema/` and Swagger is `/api/docs/`. Authentication provides CSRF, login, logout and current permissions. Public catalog uses a deliberately restricted serializer. Internal locations require authentication and mutation requires Django model permissions. Errors use DRF structured detail responses.

