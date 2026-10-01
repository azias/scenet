/**
 * The divider between the editor and the output.
 *
 * A wide strip wants most of the screen; a long document wants the editor. The divider
 * is a `role="separator"` that can be dragged, nudged with the arrow keys (Shift for
 * bigger steps), sent to either limit with Home and End, and reset with a double-click
 * or Enter. The position is written to a CSS custom property on the container, which the
 * stylesheet turns into the grid's first column.
 */

/** Neither pane may be squeezed below a fifth of the width. */
export const MIN_RATIO = 0.2;
export const MAX_RATIO = 0.8;

export function clampRatio(ratio: number): number {
  if (Number.isNaN(ratio)) return 0.5;
  return Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio));
}

/**
 * Make `handle` resize `container`'s two columns.
 *
 * @param initial - Starting share of the width for the first pane, 0 to 1.
 * @param onChange - Called with the settled ratio, to be remembered.
 */
export function installSplitter(
  container: HTMLElement,
  handle: HTMLElement,
  initial: number,
  onChange: (ratio: number) => void,
): void {
  let ratio = clampRatio(initial);

  const apply = (next: number, settled: boolean): void => {
    ratio = clampRatio(next);
    container.style.setProperty("--split", `${(ratio * 100).toFixed(2)}%`);
    handle.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    if (settled) onChange(ratio);
  };

  handle.setAttribute("aria-valuemin", String(MIN_RATIO * 100));
  handle.setAttribute("aria-valuemax", String(MAX_RATIO * 100));
  apply(ratio, false);

  let dragging = false;
  handle.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault();
    dragging = true;
    handle.classList.add("active");
    capture(handle, event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const box = container.getBoundingClientRect();
    apply((event.clientX - box.left) / box.width, false);
  });
  const release = (event: PointerEvent): void => {
    if (!dragging) return;
    dragging = false;
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    handle.classList.remove("active");
    onChange(ratio);
  };
  handle.addEventListener("pointerup", release);
  handle.addEventListener("pointercancel", release);
  handle.addEventListener("dblclick", () => apply(0.5, true));
  handle.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 0.1 : 0.02;
    const moves: Record<string, number> = {
      ArrowLeft: ratio - step,
      ArrowRight: ratio + step,
      Home: MIN_RATIO,
      End: MAX_RATIO,
      Enter: 0.5,
    };
    const next = moves[event.key];
    if (next === undefined) return;
    event.preventDefault();
    apply(next, true);
  });
}

/**
 * Keep receiving a pointer's events after it leaves the element, where the browser
 * allows it. It refuses -- by throwing -- for a pointer it no longer considers active,
 * which must not abort the drag that asked.
 */
function capture(element: Element, pointerId: number): void {
  try {
    element.setPointerCapture(pointerId);
  } catch {
    // Without capture the drag still works while the pointer stays over the element.
  }
}
