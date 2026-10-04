export function displayRole(user) {
  if (user.is_superuser) return "Admin";
  if (user.is_staff) return user.roles?.join(", ") || "Staff";
  return "Customer";
}
