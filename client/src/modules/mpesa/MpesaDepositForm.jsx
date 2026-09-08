import { MpesaCustomerTransactionForm } from "./MpesaCustomerTransactionForm";

export function MpesaDepositForm(props) {
  return (
    <MpesaCustomerTransactionForm
      {...props}
      transactionType="CUSTOMER_DEPOSIT"
    />
  );
}
