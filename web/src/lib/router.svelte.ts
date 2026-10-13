/* A hash router: #/library?folder=... . No server-side routing needed, so the
   built app can be served as plain static files. */

export interface Route {
  path: string;          // "/library"
  segments: string[];    // ["library"]
  query: URLSearchParams;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/library";
  const [pathPart, queryPart = ""] = raw.split("?");
  const path = pathPart.startsWith("/") ? pathPart : "/" + pathPart;
  return { path, segments: path.split("/").filter(Boolean), query: new URLSearchParams(queryPart) };
}

export const route: Route = $state(parse(location.hash));

function sync() {
  const next = parse(location.hash);
  route.path = next.path;
  route.segments = next.segments;
  route.query = next.query;
}

window.addEventListener("hashchange", sync);

export function href(path: string, query?: Record<string, string | number | null | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
  }
  const q = qs.toString();
  return "#" + path + (q ? "?" + q : "");
}

export function go(path: string, query?: Record<string, string | number | null | undefined>) {
  location.hash = href(path, query);
}

export function replace(path: string, query?: Record<string, string | number | null | undefined>) {
  history.replaceState(null, "", href(path, query));
  sync();
}

export const section = () => route.segments[0] ?? "library";
