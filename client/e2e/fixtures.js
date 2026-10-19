// What the API answers for a business's dashboard, kept to the fields the page needs so mocked tests stay readable.
export function dashboardSnapshot(organization) {
  return {
    organization: { business_type: "RETAIL", ...organization },
    business_date: "2026-10-19",
    generated_at: "2026-10-19T09:00:00Z",
    enabled_modules: organization.enabled_modules || [],
    today: { sales: 0, revenue: 0 },
    inventory: { total_skus: 0, low_stock: 0 },
    orders: { awaiting_payment: 0, awaiting_fulfillment: 0 },
    business_units: [],
    financial_trend: [],
  };
}
