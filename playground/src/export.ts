/**
 * Downloads: the compiled SVG, the overlay, a PNG, the Panel Core, and the source.
 *
 * Filenames follow `scenet build`, so a file saved here and one written by the command
 * line for the same document have the same name: `foo.panel.yaml` becomes `foo.svg`,
 * `foo.debug.svg` and `foo.core.json`.
 */

import { svgSize, type Size } from "./viewport.ts";

/**
 * Canvas limits. Browsers differ, and exceeding the limit does not throw -- it produces
 * a blank image. 8192 on a side is safe everywhere current; 16.7 megapixels is Safari's
 * total, the lowest of the major engines.
 */
export const MAX_CANVAS_SIDE = 8192;
export const MAX_CANVAS_AREA = 16_777_216;

export type DocumentKind = "panel" | "scene" | "script";

/** The base name for downloads: the gallery file minus its kind suffix, or `scenet`. */
export function stemFor(file: string | undefined): string {
  if (file === undefined) return "scenet";
  return file
    .replace(/\.yaml$/, "")
    .replace(/\.script$/, "")
    .replace(/\.(panel|scene)$/, "");
}

/** The source's filename, with the extension the compiler dispatches on. */
export function sourceFilename(stem: string, kind: DocumentKind): string {
  const extension = { panel: ".panel.yaml", scene: ".scene.yaml", script: ".script" }[kind];
  return `${stem}${extension}`;
}

/** The largest scale up to `wanted` at which `size` still fits on a canvas. */
export function pngScale(size: Size, wanted: number): number {
  return Math.min(
    wanted,
    MAX_CANVAS_SIDE / Math.max(size.width, size.height),
    Math.sqrt(MAX_CANVAS_AREA / (size.width * size.height)),
  );
}

/** Hand a blob to the browser as a download. */
export function download(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked later rather than at once: some browsers start the download asynchronously.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function svgBlob(svg: string): Blob {
  return new Blob([svg], { type: "image/svg+xml" });
}

export function textBlob(text: string, type = "text/plain"): Blob {
  return new Blob([text], { type: `${type};charset=utf-8` });
}

/**
 * Rasterise an SVG document to PNG at up to `wanted` times its size.
 *
 * Lettering is emitted as glyph outlines, not text, so the image needs no font and
 * looks exactly like the SVG. The blob URL keeps the image same-origin, which keeps the
 * canvas exportable, and is what the page's `img-src blob:` permits.
 */
export async function svgToPng(svg: string, wanted = 2): Promise<Blob> {
  const size = svgSize(svg);
  if (size === undefined) throw new Error("the output has no size to rasterise at");
  const scale = pngScale(size, wanted);

  const url = URL.createObjectURL(svgBlob(svg));
  try {
    const image = new Image(size.width, size.height);
    image.src = url;
    await image.decode();

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(size.width * scale);
    canvas.height = Math.round(size.height * scale);
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("this browser cannot draw to a canvas");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);

    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob === null) reject(new Error("the browser could not encode the PNG"));
        else resolve(blob);
      }, "image/png");
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
