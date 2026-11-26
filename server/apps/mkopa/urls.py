from django.urls import path
from . import api

urlpatterns = [
    path("", api.OverviewView.as_view()),
    path("phones/", api.PhonesView.as_view()),
    path("phones/<int:pk>/", api.PhoneView.as_view()),
    path("stock/", api.StockView.as_view()),
    path("stock/<int:pk>/undo/", api.StockUndoView.as_view()),
    path("rounds/", api.RoundsView.as_view()),
    path("rounds/<int:pk>/", api.RoundView.as_view()),
    path("rounds/<int:pk>/clear/", api.RoundClearView.as_view()),
    path("rounds/<int:pk>/reopen/", api.RoundReopenView.as_view()),
    path("sales/", api.SalesView.as_view()),
    path("sales/<int:pk>/undo/", api.SaleUndoView.as_view()),
    path("commission/", api.CommissionView.as_view()),
    path("commission/<int:pk>/undo/", api.CommissionUndoView.as_view()),
]
