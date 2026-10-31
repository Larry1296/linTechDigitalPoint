from .stock_check_api import StockCheckView
from django.urls import path
from .api import available_categories,dashboard,work_dashboard,staff_undos,part_books,receive,receipt_detail,receipts,transfer,variant_search,receive_defaults
urlpatterns=[path("receive/",receive),path("receipts/",receipts),path("receipts/<int:pk>/",receipt_detail),path("variants/search/",variant_search),path("variants/<int:pk>/receive-defaults/",receive_defaults),path("categories/available/",available_categories),path("transfer/",transfer),path("dashboard/",dashboard),path("dashboard/work/",work_dashboard),path("dashboard/staff-undos/",staff_undos),path("parts/<str:key>/",part_books),path("stock-check/",StockCheckView.as_view())]

from .adjustment_api import adjustments, adjustment_context
urlpatterns += [path("adjustments/", adjustments), path("adjustments/variants/<int:pk>/", adjustment_context)]

from .receipt_correction_api import receipt_line_correct
urlpatterns += [path("receipts/<int:pk>/lines/<int:line_id>/correct/", receipt_line_correct)]
from .api import receipt_return, lot_cost, variant_buying_prices, suppliers
urlpatterns += [path("receipts/<int:pk>/return/", receipt_return), path("lots/<int:pk>/cost/", lot_cost),
                path("variants/<int:pk>/buying-prices/", variant_buying_prices), path("suppliers/", suppliers)]
from .receipt_supplier_api import already_owned, pay_supplier, undo_already_owned, undo_supplier_payment
urlpatterns += [path("receipts/<int:pk>/pay-supplier/", pay_supplier), path("receipts/<int:pk>/payments/<int:entry_id>/undo/", undo_supplier_payment),
                path("receipts/<int:pk>/already-owned/", already_owned), path("receipts/<int:pk>/already-owned/undo/", undo_already_owned)]
