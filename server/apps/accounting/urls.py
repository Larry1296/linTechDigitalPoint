from .ledger_api import LedgerReportView, JournalView, ManualJournalView, JournalReverseView
from .money_check_api import MoneyCheckView, StartingMoneyView
from .loans_api import LoanCancelView, LoanRepayView, LoansView, RepaymentReverseView
from .investments_api import FundRateCheckView, InvestmentClaimView, InvestmentFundView, InvestmentMonthlyView, InvestmentMoveView, InvestmentReminderView, InvestmentRemoveView, InvestmentStatementView, InvestmentUndoView, InvestmentsView
from .statements_api import StatementsView, AccountLedgerView, ExplainSaleItemView
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import ExportView, SupplierViewSet, CategoryViewSet, AccountViewSet, EntryViewSet, ExpenseViewSet, PurchaseViewSet, ClosingViewSet, PeriodViewSet, HomeView, ReportView, SearchView, AdministrationView
router = DefaultRouter()
for route, view in [('suppliers', SupplierViewSet), ('categories', CategoryViewSet), ('accounts', AccountViewSet), ('entries', EntryViewSet), ('expenses', ExpenseViewSet), ('purchases', PurchaseViewSet), ('closings', ClosingViewSet), ('periods', PeriodViewSet)]:
    router.register(route, view)
urlpatterns = [path("money-check/", MoneyCheckView.as_view()), path("money-check/starting/", StartingMoneyView.as_view()),
               path("loans/", LoansView.as_view()), path("loans/<int:pk>/repay/", LoanRepayView.as_view()), path("loans/<int:pk>/cancel/", LoanCancelView.as_view()), path("loans/repayments/<int:pk>/reverse/", RepaymentReverseView.as_view()),
               path("investments/", InvestmentsView.as_view()), path("investments/<int:pk>/move/", InvestmentMoveView.as_view()), path("investments/<int:pk>/statement/", InvestmentStatementView.as_view()), path("investments/movements/<int:pk>/undo/", InvestmentUndoView.as_view()), path("investments/movements/<int:pk>/business/", InvestmentClaimView.as_view()), path("investments/<int:pk>/remove/", InvestmentRemoveView.as_view()), path("investments/<int:pk>/monthly/", InvestmentMonthlyView.as_view()), path("investments/reminder/", InvestmentReminderView.as_view()), path("investments/<int:pk>/fund/", InvestmentFundView.as_view()), path("investments/funds/<str:code>/check/", FundRateCheckView.as_view()),
               path("statements/", StatementsView.as_view()), path("statements/accounts/<str:code>/", AccountLedgerView.as_view()),
               path("explain/sale-items/<int:pk>/", ExplainSaleItemView.as_view()),
               path("ledger/reports/", LedgerReportView.as_view()), path("ledger/journals/", ManualJournalView.as_view()), path("ledger/journals/<int:pk>/", JournalView.as_view()), path("ledger/journals/<int:pk>/reverse/", JournalReverseView.as_view()), path("export/", ExportView.as_view()),path('home/', HomeView.as_view()), path('reports/', ReportView.as_view()), path('search/', SearchView.as_view()),
               path('administration/<str:section>/', AdministrationView.as_view()), path('', include(router.urls))]
