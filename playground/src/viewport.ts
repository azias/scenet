/**
 * Zoom and pan for the compiled output.
 *
 * The output used to be shown at "fit" and nothing else, which made a ten-panel strip
 * an unreadable 11% sliver. This is a small, dependency-free viewer: the SVG sits at its
 * own size inside a stage, and the stage is moved with one CSS transform. Vector output
 * re-rasterises at whatever scale the transform asks for, so there is no resolution to
 * lose by zooming in.
 *
 * The arithmetic is exported separately from the DOM wiring so it can be tested under
 * Node, where there is no DOM.
 */

/** Where the stage is: scaled by `scale`, then moved to (`x`, `y`) in viewport pixels. */
export interface Transform {
  readonly scale: number;
  readonly x: number;
  readonly y: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** 2% shows a long strip whole on a phone; 1600% is past where a line has any detail. */
export const MIN_SCALE = 0.02;
export const MAX_SCALE = 16;

/** Breathing room around the content when it is fitted. */
const FIT_PADDING = 16;

/** Each press of a zoom button or key, and the amount an arrow key pans. */
const STEP = 1.25;
const PAN_STEP = 48;

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/** The transform that shows all of `content`, centred, inside `viewport` less padding. */
export function fitTransform(content: Size, viewport: Size, padding = FIT_PADDING): Transform {
  const room = {
    width: Math.max(1, viewport.width - 2 * padding),
    height: Math.max(1, viewport.height - 2 * padding),
  };
  const scale = clampScale(Math.min(room.width / content.width, room.height / content.height));
  return centred(content, viewport, scale);
}

/** The content at 100%, centred. */
export function actualSize(content: Size, viewport: Size): Transform {
  return centred(content, viewport, 1);
}

function centred(content: Size, viewport: Size, scale: number): Transform {
  return {
    scale,
    x: (viewport.width - content.width * scale) / 2,
    y: (viewport.height - content.height * scale) / 2,
  };
}

/**
 * Zoom by `factor`, keeping the content point under `at` exactly where it is.
 *
 * At a limit the transform is returned unchanged rather than re-anchored, so holding a
 * zoom key at 1600% does not slowly slide the picture away.
 */
export function zoomAt(t: Transform, factor: number, at: Point): Transform {
  const scale = clampScale(t.scale * factor);
  if (scale === t.scale) return t;
  const ratio = scale / t.scale;
  return { scale, x: at.x - (at.x - t.x) * ratio, y: at.y - (at.y - t.y) * ratio };
}

/**
 * How much one wheel event zooms.
 *
 * Exponential in the distance, so scrolling down by some amount and back up by the
 * same amount returns to the same scale. A trackpad pinch reaches the page as a wheel
 * event with `ctrlKey` set and small deltas, so it gets a higher sensitivity.
 *
 * @param deltaY - The event's `deltaY`.
 * @param deltaMode - The event's `deltaMode`: 0 pixels, 1 lines, 2 pages.
 * @param pinch - Whether `ctrlKey` was set.
 */
export function wheelFactor(deltaY: number, deltaMode: number, pinch: boolean): number {
  const pixels = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(-pixels * (pinch ? 0.01 : 0.0015));
}

/**
 * The size an SVG document declares on its root element.
 *
 * Read from the markup rather than measured, so it is known before the SVG is in the
 * page -- and so the PNG export can use it too. Every SVG the compiler emits carries a
 * `width` and `height`; the `viewBox` is the fallback.
 */
export function svgSize(markup: string): Size | undefined {
  const root = /<svg\b[^>]*>/.exec(markup)?.[0];
  if (root === undefined) return undefined;
  const number = (name: string): number | undefined => {
    const value = new RegExp(`\\s${name}="([0-9.]+)"`).exec(root)?.[1];
    return value === undefined ? undefined : Number(value);
  };
  const width = number("width");
  const height = number("height");
  if (width !== undefined && height !== undefined && width > 0 && height > 0) {
    return { width, height };
  }
  const box = /\sviewBox="[-0-9.]+ [-0-9.]+ ([0-9.]+) ([0-9.]+)"/.exec(root);
  if (box?.[1] !== undefined && box[2] !== undefined) {
    return { width: Number(box[1]), height: Number(box[2]) };
  }
  return undefined;
}

/**
 * The viewer itself: a host element that receives input and a stage that is moved.
 *
 * Mouse wheel zooms around the cursor, dragging pans, two fingers pinch, double-click
 * toggles between Fit and 100%, and with the host focused `+` `-` `0` `1` and the arrow
 * keys do what they say.
 *
 * It remembers whether the user has taken control. Until they do, it stays fitted --
 * through recompiles and window resizes. Once they have zoomed or panned, a recompile
 * that produces an SVG of the same size leaves the view alone, so editing a line of
 * dialogue while zoomed in on its balloon does not throw the view back to Fit.
 */
export class Viewport {
  readonly #host: HTMLElement;
  readonly #stage: HTMLElement;
  readonly #onChange: (transform: Transform) => void;

  #transform: Transform = { scale: 1, x: 0, y: 0 };
  #content: Size | undefined;
  #markup = "";
  #fitted = true;

  readonly #pointers = new Map<number, Point>();
  #pinch: { distance: number; centre: Point } | undefined;

  constructor(host: HTMLElement, stage: HTMLElement, onChange: (transform: Transform) => void) {
    this.#host = host;
    this.#stage = stage;
    this.#onChange = onChange;

    host.addEventListener("wheel", (event) => this.#wheel(event), { passive: false });
    host.addEventListener("pointerdown", (event) => this.#pointerDown(event));
    host.addEventListener("pointermove", (event) => this.#pointerMove(event));
    host.addEventListener("pointerup", (event) => this.#pointerUp(event));
    host.addEventListener("pointercancel", (event) => this.#pointerUp(event));
    host.addEventListener("dblclick", (event) => this.#doubleClick(event));
    host.addEventListener("keydown", (event) => this.#key(event));
    new ResizeObserver(() => {
      if (this.#fitted) this.fit();
    }).observe(host);
  }

  get scale(): number {
    return this.#transform.scale;
  }

  /** Show an SVG document, keeping the view if the user has one and the size held. */
  show(markup: string): void {
    if (markup === this.#markup) return;
    this.#markup = markup;
    // Safe for the reason given where the compiler's output is first handled: every
    // identifier and line of dialogue is escaped into its attribute or element.
    this.#stage.innerHTML = markup;
    const size = svgSize(markup);
    const svg = this.#stage.querySelector("svg");
    if (size === undefined || svg === null) return;
    svg.style.width = `${size.width}px`;
    svg.style.height = `${size.height}px`;

    const resized =
      this.#content === undefined ||
      this.#content.width !== size.width ||
      this.#content.height !== size.height;
    this.#content = size;
    if (resized || this.#fitted) {
      this.fit();
    } else {
      this.#apply();
    }
  }

  /** Fit the current content, and keep fitting until the user takes control again. */
  fit(): void {
    this.#fitted = true;
    if (this.#content === undefined) return;
    this.#set(fitTransform(this.#content, this.#viewportSize()));
  }

  actualSize(): void {
    if (this.#content === undefined) return;
    this.#fitted = false;
    this.#set(actualSize(this.#content, this.#viewportSize()));
  }

  /** Zoom around the centre of the view, as the toolbar buttons do. */
  zoomBy(factor: number): void {
    const { width, height } = this.#viewportSize();
    this.#zoom(factor, { x: width / 2, y: height / 2 });
  }

  zoomIn(): void {
    this.zoomBy(STEP);
  }

  zoomOut(): void {
    this.zoomBy(1 / STEP);
  }

  #zoom(factor: number, at: Point): void {
    this.#fitted = false;
    this.#set(zoomAt(this.#transform, factor, at));
  }

  #pan(dx: number, dy: number): void {
    this.#fitted = false;
    const t = this.#transform;
    this.#set({ scale: t.scale, x: t.x + dx, y: t.y + dy });
  }

  #set(transform: Transform): void {
    this.#transform = transform;
    this.#apply();
  }

  #apply(): void {
    const { scale, x, y } = this.#transform;
    this.#stage.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    this.#onChange(this.#transform);
  }

  #viewportSize(): Size {
    return { width: this.#host.clientWidth, height: this.#host.clientHeight };
  }

  /** A point in the host's own coordinates, which is what the transform is in. */
  #local(event: { clientX: number; clientY: number }): Point {
    const box = this.#host.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  #wheel(event: WheelEvent): void {
    if (this.#content === undefined) return;
    event.preventDefault();
    this.#zoom(wheelFactor(event.deltaY, event.deltaMode, event.ctrlKey), this.#local(event));
  }

  #pointerDown(event: PointerEvent): void {
    if (this.#content === undefined) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    try {
      this.#host.setPointerCapture(event.pointerId);
    } catch {
      // Refused for a pointer the browser no longer tracks; the drag works without it.
    }
    this.#pointers.set(event.pointerId, this.#local(event));
    this.#host.classList.add("dragging");
    this.#pinch = this.#pinchState();
  }

  #pointerMove(event: PointerEvent): void {
    const previous = this.#pointers.get(event.pointerId);
    if (previous === undefined) return;
    const current = this.#local(event);
    this.#pointers.set(event.pointerId, current);

    if (this.#pointers.size === 1) {
      this.#pan(current.x - previous.x, current.y - previous.y);
      return;
    }
    const before = this.#pinch;
    const after = this.#pinchState();
    if (before === undefined || after === undefined) return;
    // Pan with the fingers' midpoint, then zoom about it by the change in spread.
    this.#pan(after.centre.x - before.centre.x, after.centre.y - before.centre.y);
    this.#zoom(after.distance / before.distance, after.centre);
    this.#pinch = after;
  }

  #pointerUp(event: PointerEvent): void {
    this.#pointers.delete(event.pointerId);
    this.#pinch = this.#pinchState();
    if (this.#pointers.size === 0) this.#host.classList.remove("dragging");
  }

  #pinchState(): { distance: number; centre: Point } | undefined {
    const [a, b] = [...this.#pointers.values()];
    if (a === undefined || b === undefined) return undefined;
    return {
      distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
      centre: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
    };
  }

  #doubleClick(event: MouseEvent): void {
    if (this.#content === undefined) return;
    if (this.#fitted) {
      // To 100%, about the point that was clicked: the natural way to ask to see it.
      this.#zoom(1 / this.#transform.scale, this.#local(event));
    } else {
      this.fit();
    }
  }

  #key(event: KeyboardEvent): void {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const actions: Record<string, () => void> = {
      "+": () => this.zoomIn(),
      "=": () => this.zoomIn(),
      "-": () => this.zoomOut(),
      "0": () => this.fit(),
      "1": () => this.actualSize(),
      ArrowLeft: () => this.#pan(PAN_STEP, 0),
      ArrowRight: () => this.#pan(-PAN_STEP, 0),
      ArrowUp: () => this.#pan(0, PAN_STEP),
      ArrowDown: () => this.#pan(0, -PAN_STEP),
    };
    const action = actions[event.key];
    if (action === undefined) return;
    event.preventDefault();
    action();
  }
}
