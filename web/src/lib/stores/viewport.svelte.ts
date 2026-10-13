/* Is this a phone-sized screen, or a touch one? Components read these for
   behaviour (the folder drawer, the info sheet, a week calendar by default);
   plain styling uses the same breakpoints in CSS. */

export const PHONE_QUERY = "(max-width: 760px)";
export const COARSE_QUERY = "(pointer: coarse)";

export const viewport = $state({ phone: false, coarse: false });

function watch(query: string, key: "phone" | "coarse") {
  if (typeof window === "undefined" || !window.matchMedia) return;
  const mq = window.matchMedia(query);
  viewport[key] = mq.matches;
  mq.addEventListener("change", (e) => { viewport[key] = e.matches; });
}

watch(PHONE_QUERY, "phone");
watch(COARSE_QUERY, "coarse");
