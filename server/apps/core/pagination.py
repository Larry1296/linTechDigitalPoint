from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class OptionalPages(PageNumberPagination):
    """Pages only when asked (?page=N), so a list that grows every day loads one page at a time while
    callers that want every row (counts, pickers) keep getting the plain list."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if "page" not in request.query_params:
            return None
        # A page past the end (its last rows were just deleted) gives the last page instead of an error.
        self.request = request
        paginator = self.django_paginator_class(queryset, self.get_page_size(request))
        number = request.query_params.get("page")
        number = int(number) if str(number).isdigit() and int(number) > 0 else 1
        self.page = paginator.page(min(number, paginator.num_pages))
        return list(self.page)

    def get_paginated_response(self, data):
        page = self.page
        return Response({"count": page.paginator.count, "page": page.number, "pages": page.paginator.num_pages,
                         "page_size": page.paginator.per_page, "results": data})


def page_or_list(request, rows, to_row, cap=None):
    """For a plain view: one page of `rows` when ?page=N is asked (every row reachable, page by page),
    else the plain list (cut to `cap` rows when given, as before)."""
    pager = OptionalPages()
    page = pager.paginate_queryset(rows, request)
    if page is None:
        return Response([to_row(row) for row in (rows[:cap] if cap else rows)])
    return pager.get_paginated_response([to_row(row) for row in page])
