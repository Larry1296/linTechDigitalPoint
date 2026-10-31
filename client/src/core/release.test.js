import { afterEach, expect, it, vi } from "vitest";
import { newReleaseOut } from "./release";

const page = (src) => `<!doctype html><html><head><script type="module" crossorigin src="${src}"></script></head><body></body></html>`;
const running = (src) => {
  const script = document.createElement("script");
  script.type = "module";
  script.setAttribute("src", src);
  document.head.append(script);
};
afterEach(() => { document.head.innerHTML = ""; vi.unstubAllGlobals(); });

it("sees a newer release when the live page loads a different build", async () => {
  running("/assets/index-old111.js");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(page("/assets/index-new222.js"))));
  expect(await newReleaseOut()).toBe(true);
  expect(fetch).toHaveBeenCalledWith("/", expect.objectContaining({ cache: "no-store" }));
});

it("stays put on the same build, offline, or on the development server", async () => {
  running("/assets/index-old111.js");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(page("/assets/index-old111.js"))));
  expect(await newReleaseOut()).toBe(false);
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
  expect(await newReleaseOut()).toBe(false);
  document.head.innerHTML = "";
  running("/src/main.jsx");
  expect(await newReleaseOut()).toBe(false);
});

it("reloads at once to a new release when nothing has been typed, and waits for the next page when something has", async () => {
  const { renderHook, act } = await import("@testing-library/react");
  const { MemoryRouter } = await import("react-router-dom");
  const { useReloadOnNewRelease } = await import("./release");
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  running("/assets/index-old111.js");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(page("/assets/index-new222.js"))));
  const first = renderHook(() => useReloadOnNewRelease(), { wrapper: MemoryRouter });
  await act(async () => {});
  expect(reload).toHaveBeenCalledTimes(1);
  first.unmount();
  reload.mockClear();
  const box = document.createElement("input");
  document.body.append(box);
  vi.stubGlobal("fetch", vi.fn(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));  // the person types while the check is on its way
    box.dispatchEvent(new Event("input", { bubbles: true }));
    return new Response(page("/assets/index-new222.js"));
  }));
  renderHook(() => useReloadOnNewRelease(), { wrapper: MemoryRouter });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  expect(reload).not.toHaveBeenCalled();
  box.remove();
});
