/**
 * Keeping a document: an autosaved draft, and share links.
 *
 * **A share link carries the whole document in the URL fragment.** The fragment is
 * never sent to a server, so sharing involves no backend and no third party -- which
 * this page has none of, and its Content-Security-Policy would refuse anyway. The text
 * is deflated and base64url-encoded, which makes a typical panel a link of a few
 * hundred characters.
 *
 * **The draft lives in `localStorage`**, which can be unavailable or throw: a private
 * window, blocked site data, a full quota. Every access is wrapped, and every reader
 * treats what it finds as untrusted, because it may have been written by an older
 * version of this page.
 */

/** The fragment key a share link uses: `#src=<token>`. */
const SHARE_KEY = "src";

/** Namespace for everything this page keeps in storage. */
const PREFIX = "scenet.playground.";
const DRAFT_KEY = `${PREFIX}draft`;

/**
 * The most a share link may inflate to. A link is untrusted input, and a few hundred
 * bytes of deflate can expand to gigabytes; the largest gallery document is under 4 kB.
 */
export const MAX_SOURCE_BYTES = 512 * 1024;

/** The parts of `Storage` used here, so tests can supply their own. */
export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** What is autosaved: the text, and which gallery example it started from (or -1). */
export interface Draft {
  readonly source: string;
  readonly example: number;
}

/** Compress a document into a token that is safe in a URL fragment as it stands. */
export async function encodeSource(source: string): Promise<string> {
  const packed = await pipe(new TextEncoder().encode(source), new CompressionStream("deflate-raw"));
  return toBase64Url(packed);
}

/**
 * Recover a document from a token.
 *
 * @throws Error - The token is not base64url, does not inflate, or inflates past
 *   {@link MAX_SOURCE_BYTES}.
 */
export async function decodeSource(token: string): Promise<string> {
  const packed = fromBase64Url(token);
  const text = await pipe(packed, new DecompressionStream("deflate-raw"), MAX_SOURCE_BYTES);
  return new TextDecoder("utf-8", { fatal: true }).decode(text);
}

/** The token in a location fragment, if it is a share link. */
export function tokenFromHash(hash: string): string | undefined {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get(SHARE_KEY);
  return token === null || token === "" ? undefined : token;
}

/** `base` with its fragment replaced by a share token. */
export function shareUrl(base: string, token: string): string {
  const url = new URL(base);
  url.hash = `${SHARE_KEY}=${token}`;
  return url.href;
}

export function loadDraft(store: KeyValueStore | undefined): Draft | undefined {
  const raw = read(store, DRAFT_KEY);
  if (raw === undefined) return undefined;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "source" in value &&
      "example" in value &&
      typeof value.source === "string" &&
      typeof value.example === "number"
    ) {
      return { source: value.source, example: value.example };
    }
  } catch {
    // Corrupt, or written by a different version of this page: treated as absent.
  }
  return undefined;
}

export function saveDraft(store: KeyValueStore | undefined, draft: Draft): void {
  write(store, DRAFT_KEY, JSON.stringify(draft));
}

export function clearDraft(store: KeyValueStore | undefined): void {
  try {
    store?.removeItem(DRAFT_KEY);
  } catch {
    // Nothing to do: if storage is refusing, there is no draft in it either.
  }
}

/** A remembered number, such as the split position, or `fallback`. */
export function loadNumber(store: KeyValueStore | undefined, name: string, fallback: number): number {
  const raw = read(store, PREFIX + name);
  const value = raw === undefined ? Number.NaN : Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function saveNumber(store: KeyValueStore | undefined, name: string, value: number): void {
  write(store, PREFIX + name, String(value));
}

/** The page's `localStorage`, or undefined where touching it throws. */
export function browserStore(): KeyValueStore | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

function read(store: KeyValueStore | undefined, key: string): string | undefined {
  try {
    return store?.getItem(key) ?? undefined;
  } catch {
    return undefined;
  }
}

function write(store: KeyValueStore | undefined, key: string, value: string): void {
  try {
    store?.setItem(key, value);
  } catch {
    // Quota or policy. Losing an autosave is better than breaking the editor over it.
  }
}

/** Run bytes through a transform stream, refusing output beyond `limit` bytes. */
async function pipe(
  input: Uint8Array<ArrayBuffer>,
  transform: TransformStream<BufferSource, Uint8Array<ArrayBuffer>>,
  limit = Number.POSITIVE_INFINITY,
): Promise<Uint8Array<ArrayBuffer>> {
  const reader = new Blob([input]).stream().pipeThrough(transform).getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      throw new Error(`shared document is too large (over ${limit} bytes)`);
    }
    chunks.push(value);
  }
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  // In slices, because spreading a large array into one call overflows the stack.
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64Url(token: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9_-]*$/.test(token)) {
    throw new Error("share token is not base64url");
  }
  const binary = atob(token.replaceAll("-", "+").replaceAll("_", "/"));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
