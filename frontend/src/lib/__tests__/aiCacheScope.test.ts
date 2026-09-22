import { describe, it, expect, beforeEach } from "vitest";
import { AI_CACHE_PREFIX, clearToken, getUserScope, setToken } from "@/lib/api";

// This jsdom build exposes a `localStorage` object with no methods; install a real
// in-memory Storage so the scoping under test actually runs.
function installStorage() {
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, String(value)),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() {
        return store.size;
      },
    },
  });
}

function tokenFor(subject: string): string {
  const payload = btoa(JSON.stringify({ sub: subject }));
  return `header.${payload}.signature`;
}

describe("AI analysis cache scoping", () => {
  beforeEach(() => installStorage());

  it("records the signed-in user as the cache scope", () => {
    setToken(tokenFor("user-a"));
    expect(getUserScope()).toBe("user-a");
  });

  it("drops cached analyses when a different user signs in", () => {
    setToken(tokenFor("user-a"));
    localStorage.setItem(`${AI_CACHE_PREFIX}user-a:sec-1`, "{}");

    setToken(tokenFor("user-b"));

    expect(localStorage.getItem(`${AI_CACHE_PREFIX}user-a:sec-1`)).toBeNull();
    expect(getUserScope()).toBe("user-b");
  });

  it("keeps cached analyses when the same user re-authenticates", () => {
    setToken(tokenFor("user-a"));
    localStorage.setItem(`${AI_CACHE_PREFIX}user-a:sec-1`, "{}");

    setToken(tokenFor("user-a"));

    expect(localStorage.getItem(`${AI_CACHE_PREFIX}user-a:sec-1`)).toBe("{}");
  });

  it("clears every cached analysis on logout", () => {
    setToken(tokenFor("user-a"));
    localStorage.setItem(`${AI_CACHE_PREFIX}user-a:sec-1`, "{}");
    localStorage.setItem(`${AI_CACHE_PREFIX}user-a:sec-2`, "{}");
    localStorage.setItem("unrelated_preference", "keep-me");

    clearToken();

    expect(localStorage.getItem(`${AI_CACHE_PREFIX}user-a:sec-1`)).toBeNull();
    expect(localStorage.getItem(`${AI_CACHE_PREFIX}user-a:sec-2`)).toBeNull();
    expect(localStorage.getItem("unrelated_preference")).toBe("keep-me");
    expect(getUserScope()).toBe("anon");
  });

  it("drops caches when the token cannot be read at all", () => {
    setToken(tokenFor("user-a"));
    localStorage.setItem(`${AI_CACHE_PREFIX}user-a:sec-1`, "{}");

    setToken("not-a-jwt");

    expect(localStorage.getItem(`${AI_CACHE_PREFIX}user-a:sec-1`)).toBeNull();
  });
});
