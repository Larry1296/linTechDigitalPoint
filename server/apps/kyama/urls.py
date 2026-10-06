from django.urls import path
from . import api

urlpatterns = [
    path("", api.KyamaListView.as_view()),
    path("setup/", api.KyamaSetupView.as_view()),
    path("<int:pk>/", api.KyamaDetailView.as_view()),
    path("<int:pk>/members/", api.MembersView.as_view()),
    path("<int:pk>/members/<int:member_pk>/", api.MemberView.as_view()),
    path("<int:pk>/members/<int:member_pk>/leave/", api.MemberLeaveView.as_view()),
    path("<int:pk>/turns/", api.TurnsView.as_view()),
    path("<int:pk>/next-receiver/", api.NextReceiverView.as_view()),
    path("<int:pk>/payments/", api.PaymentsView.as_view()),
    path("<int:pk>/excuses/", api.ExcusesView.as_view()),
    path("<int:pk>/payouts/", api.PayoutsView.as_view()),
    path("payments/<int:pk>/reverse/", api.PaymentReverseView.as_view()),
    path("payouts/<int:pk>/reverse/", api.PayoutReverseView.as_view()),
    path("dues/<int:pk>/waive-fine/", api.WaiveFineView.as_view()),
]
