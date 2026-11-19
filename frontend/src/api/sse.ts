export type SseEvent = {
  event: string;
  data: unknown;
};

export class SseError extends Error {
  readonly code: "buffer_exceeded";

  constructor(code: "buffer_exceeded", message: string) {
    super(message);
    this.name = "SseError";
    this.code = code;
  }
}

/** Hard cap for an unterminated frame buffer to avoid unbounded memory growth. */
export const MAX_SSE_BUFFER_CHARS = 1_000_000;

function parseBlock(block: string): SseEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    return { event: eventName, data: JSON.parse(dataLines.join("\n")) as unknown };
  } catch {
    return null;
  }
}

/**
 * Parses an SSE byte stream (POST + fetch/ReadableStream).
 *
 * Handles events split across chunks, several events per chunk, CRLF/CR line
 * endings, comments, multibyte UTF-8 (streaming TextDecoder) and blank-line
 * framing. Incomplete trailing frames are dropped; the caller must treat a
 * stream that ends without a terminal event as interrupted.
 */
export async function* parseSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finished = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        finished = true;
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > MAX_SSE_BUFFER_CHARS) {
        throw new SseError(
          "buffer_exceeded",
          "SSE frame exceeded the maximum buffered size.",
        );
      }

      for (;;) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (separator === null || separator.index === undefined) {
          break;
        }
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const event = parseBlock(block);
        if (event !== null) {
          yield event;
        }
      }
    }
  } finally {
    if (!finished) {
      try {
        await reader.cancel();
      } catch {
        // The underlying transport may already be closed.
      }
    }
    reader.releaseLock();
  }
}