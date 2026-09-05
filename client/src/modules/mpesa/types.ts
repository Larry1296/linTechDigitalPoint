export type MpesaOutlet = { id: number; display_name: string; agent_reference: string; active: boolean };
export type MpesaSession = { id: number; outlet: number; status: string; opening_cash: string; opening_float: string; current_cash: string; current_float: string; opened_at: string };
export type MpesaTransaction = { id: number; internal_reference: string; transaction_type: string; amount: string; cash_delta: string; float_delta: string; provider_reference: string | null; occurred_at: string; reversal_of: number | null };
export type MpesaDashboard = { session: MpesaSession | null; cash: string; float: string; deposits: string; withdrawals: string; transaction_count: number; commission: string; principal_revenue: number; transaction_volume: string };
