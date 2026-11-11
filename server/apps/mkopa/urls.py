from django.urls import path
from . import api

urlpatterns = [
    path("", api.OverviewView.as_view()),
    path("phones/", api.PhonesView.as_view()),
    path("phones/<int:pk>/", api.PhoneView.as_view()),
    path("stock/", api.StockView.as_view()),
    path("stock/<int:pk>/undo/", api.StockUndoView.as_view()),
    path("sales/", api.SalesView.as_view()),
    path("sales/<int:pk>/undo/", api.SaleUndoView.as_view()),
    path("commission/", api.CommissionView.as_view()),
    path("commission/<int:pk>/undo/", api.CommissionUndoView.as_view()),
]
