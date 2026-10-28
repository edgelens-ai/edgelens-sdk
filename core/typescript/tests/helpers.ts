/**
 * Test helpers — a `fetch` stub that records calls and returns
 * canned responses keyed by `${METHOD} ${pathname}`.
 */

export interface FakeCall {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string | undefined;
  rawBody: BodyInit | null | undefined;
}

export interface FakeResponse {
  status?: number;
  json?: unknown;
  body?: string;
  headers?: Record<string, string>;
}

type Handler = FakeResponse | ((req: FakeCall) => FakeResponse);

export interface FakeFetch {
  fetch: typeof fetch;
  calls: FakeCall[];
  on(method: string, pathname: string, handler: Handler): FakeFetch;
}

export function makeFetch(): FakeFetch {
  const calls: FakeCall[] = [];
  const handlers = new Map<string, Handler>();

  const fetchImpl: typeof fetch = async (input, init) => {
    const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
    const u = new URL(url);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${u.pathname}`;
    const headers: Record<string, string> = {};
    new Headers(init?.headers as HeadersInit).forEach((v, k) => {
      headers[k] = v;
    });
    const body =
      typeof init?.body === "string"
        ? init.body
        : init?.body === undefined || init.body === null
          ? undefined
          : "(non-string body)";
    const call: FakeCall = { method, url, headers, body, rawBody: init?.body };
    calls.push(call);

    const handler = handlers.get(key);
    if (!handler) {
      return new Response(JSON.stringify({ error: `no handler for ${key}` }), {
        status: 599,
        headers: { "content-type": "application/json" },
      });
    }
    const res = typeof handler === "function" ? handler(call) : handler;
    const init2: ResponseInit = {
      status: res.status ?? 200,
      headers: {
        "content-type": res.json !== undefined ? "application/json" : "text/plain",
        ...(res.headers ?? {}),
      },
    };
    const payload = res.json !== undefined ? JSON.stringify(res.json) : (res.body ?? "");
    return new Response(payload, init2);
  };

  const wrapper: FakeFetch = {
    fetch: fetchImpl,
    calls,
    on(method, pathname, handler) {
      handlers.set(`${method.toUpperCase()} ${pathname}`, handler);
      return wrapper;
    },
  };
  return wrapper;
}
