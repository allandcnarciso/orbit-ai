import { describe, expect, it } from "vitest";

import { parseSse, MAX_SSE_BUFFER_CHARS, SseError } from "../api/sse";
import type { SseEvent } from "../api/sse";

function streamFromBytes(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

async function collect(
  raw: string,
  chunkSize?: number,
): Promise<SseEvent[]> {
  const bytes = new TextEncoder().encode(raw);
  const chunks: Uint8Array[] = [];
  if (chunkSize === undefined) {
    chunks.push(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += chunkSize) {
      chunks.push(bytes.slice(index, index + chunkSize));
    }
  }
  const events: SseEvent[] = [];
  for await (const event of parseSse(streamFromBytes(chunks))) {
    events.push(event);
  }
  return events;
}

const RAW =
  'event: message.started\ndata: {"message_id":"m1","provider":"fake"}\n\n' +
  'event: content.delta\ndata: {"message_id":"m1","delta":"Olá 🌍"}\n\n' +
  'event: message.completed\ndata: {"message_id":"m1","content":"Olá 🌍"}\n\n';

describe("parseSse", () => {
  it("ignores keep-alive comment frames between events", async () => {
    const raw =
      ': keep-alive\n\nevent: message.started\ndata: {"message_id":"m1"}\n\n' +
      ": keep-alive\n\n: keep-alive\n\nevent: message.completed\ndata: {\"message_id\":\"m1\"}\n\n";

    const events = await collect(raw);
    expect(events.map((event) => event.event)).toEqual([
      "message.started",
      "message.completed",
    ]);
  });

  it("parses multiple events from a single chunk", async () => {
    const events = await collect(RAW);
    expect(events.map((event) => event.event)).toEqual([
      "message.started",
      "content.delta",
      "message.completed",
    ]);
    expect(events[1]?.data).toEqual({ message_id: "m1", delta: "Olá 🌍" });
  });

  it("handles events fragmented across byte chunks, including multibyte UTF-8", async () => {
    const events = await collect(RAW, 3);
    expect(events).toHaveLength(3);
    expect(events[1]?.data).toEqual({ message_id: "m1", delta: "Olá 🌍" });
  });

  it("supports CRLF framing and comments", async () => {
    const raw =
      ": keep-alive\r\n\r\n" +
      'event: content.delta\r\ndata: {"delta":"a"}\r\n\r\n' +
      'event: content.delta\r\ndata: {"delta":"b"}\r\n\r\n';
    const events = await collect(raw);
    expect(events.map((event) => event.data)).toEqual([
      { delta: "a" },
      { delta: "b" },
    ]);
  });

  it("skips malformed JSON and blocks without data", async () => {
    const raw =
      "event: content.delta\ndata: {not-json}\n\n" +
      "event: content.delta\n\n" +
      'event: content.delta\ndata: {"delta":"ok"}\n\n';
    const events = await collect(raw);
    expect(events).toEqual([
      { event: "content.delta", data: { delta: "ok" } },
    ]);
  });

  it("drops an incomplete trailing frame", async () => {
    const raw = 'event: content.delta\ndata: {"delta":"lost"}\n';
    expect(await collect(raw)).toEqual([]);
  });

  it("emits no events for an empty stream", async () => {
    expect(await collect("")).toEqual([]);
  });

  it("cancels the reader when the consumer stops early", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('event: content.delta\ndata: {"delta":"a"}\n\n'),
        );
      },
      cancel() {
        cancelled = true;
      },
    });

    const iterator = parseSse(stream);
    await iterator.next();
    await iterator.return(undefined);

    expect(cancelled).toBe(true);
  });

  it("rejects an unterminated frame that exceeds the buffer cap", async () => {
    const huge = `data: ${"x".repeat(MAX_SSE_BUFFER_CHARS + 10)}`;
    const stream = streamFromBytes([new TextEncoder().encode(huge)]);

    await expect(
      (async () => {
        for await (const event of parseSse(stream)) {
          void event;
        }
      })(),
    ).rejects.toBeInstanceOf(SseError);
  });
});