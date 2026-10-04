# Frontend components

Keep shared UI in `components/`, domain UI alongside its module, and stateful
operations in `core/` or a module hook. Pages compose these pieces and own their
route-specific content. Preserve native HTML semantics and existing CSS classes
when extracting markup.

## Shared UI

- `components/forms/FormField.jsx`: labeled native input; accepts children for a
  select, textarea, or other custom control. Native props such as `required`,
  `min`, `max`, `autoComplete`, and `onChange` pass through to the input.
- `components/forms/PasswordField.jsx`: labeled password input with its own
  accessible visibility toggle. Visibility is local to each field.
- `components/dashboard/MetricCard.jsx`: label and value for dashboard metrics.
- `components/navigation/SidebarNavigation.jsx`: sectioned icon links. The caller
  filters permissions and supplies the menu-close callback.
- `components/States.jsx`: loading, empty, and error states.
- `components/AppChrome.jsx`: shared branding, navbar, and footer.

## Domain components and operations

- `modules/storefront/components/`: product lookup presentation components are
  reused by internal product and POS screens. They do not expose public prices
  or shopping actions.
- `modules/auth/AuthFormCard.jsx`: shared authentication form shell.
- `modules/auth/useAuthForm.js`: internal staff login, session refresh, and safe
  post-authentication navigation.
- `core/auth/useSignOut.js`: shared confirmation and logout.
- `modules/mpesa/MpesaCustomerTransactionForm.jsx`: retained for optional
  walk-in transaction references; it does not create customer accounts.

Extend a shared component when the behavior is the same. Keep domain-specific
validation and workflows in their module rather than adding unrelated modes to
universal components. Do not copy API mutations into presentation components.

Run `npm test`, `npm run lint`, and `npm run build` from `client/`. Browser tests
use `npm run test:e2e` with a frontend server on port 5174 (or `E2E_BASE_URL`).
