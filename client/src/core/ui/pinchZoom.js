// A two-finger pinch on a laptop touchpad zooms the page in by accident. The zoomed page then slides sideways
// under every two-finger swipe (sidebar and footer included) until Ctrl + 0 is pressed. Browsers deliver the
// pinch as a wheel event with ctrlKey set (Safari as gesture events), so those are cancelled here. Deliberate
// zoom still works with Ctrl + and Ctrl − or the browser menu, which enlarge the page without making it slide.
export function preventPinchZoom(target = window) {
  const cancel = (event) => { if (event.type !== "wheel" || event.ctrlKey) event.preventDefault(); };
  const options = { passive: false };
  target.addEventListener("wheel", cancel, options);
  for (const type of ["gesturestart", "gesturechange"]) target.addEventListener(type, cancel, options);
  return () => {
    target.removeEventListener("wheel", cancel, options);
    for (const type of ["gesturestart", "gesturechange"]) target.removeEventListener(type, cancel, options);
  };
}
