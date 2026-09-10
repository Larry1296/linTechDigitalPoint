export function rememberListingPosition(key) {
  try {
    sessionStorage.setItem(`listing-position:${key}`, String(window.scrollY));
  } catch {
    /* Navigation still works when browser storage is unavailable. */
  }
}

export function restoreListingPosition(key) {
  try {
    const saved = sessionStorage.getItem(`listing-position:${key}`);
    if (saved === null || !Number.isFinite(Number(saved))) return false;
    window.scrollTo({ top: Number(saved), behavior: "instant" });
    return true;
  } catch {
    return false;
  }
}
