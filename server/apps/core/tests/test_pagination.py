import pytest
from django.test import RequestFactory
from rest_framework.request import Request

from apps.core.pagination import OptionalPages, page_or_list


def request(query=""):
    return Request(RequestFactory().get("/x/" + query))


def test_a_list_is_paged_only_when_a_page_is_asked_for():
    rows = list(range(25))
    assert page_or_list(request(), rows, lambda n: n).data == rows
    assert page_or_list(request(), rows, lambda n: n, cap=5).data == [0, 1, 2, 3, 4]
    body = page_or_list(request("?page=2"), rows, lambda n: n * 10).data
    assert body == {"count": 25, "page": 2, "pages": 3, "page_size": 10, "results": [100, 110, 120, 130, 140, 150, 160, 170, 180, 190]}


@pytest.mark.parametrize("asked,page", [("?page=99", 3), ("?page=0", 1), ("?page=abc", 1)])
def test_a_page_past_the_end_or_not_a_number_gives_a_real_page(asked, page):
    assert page_or_list(request(asked), list(range(25)), lambda n: n).data["page"] == page


def test_an_empty_list_has_one_empty_page_and_the_size_is_capped():
    assert page_or_list(request("?page=1"), [], lambda n: n).data == {"count": 0, "page": 1, "pages": 1, "page_size": 10, "results": []}
    assert OptionalPages().get_page_size(request("?page=1&page_size=5000")) == 100
