import { MpesaCustomerTransactionForm } from "./MpesaCustomerTransactionForm";

export function MpesaWithdrawalForm(props) {
  return (
    <MpesaCustomerTransactionForm
      {...props}
      transactionType="CUSTOMER_WITHDRAWAL"
    />
  );
}
