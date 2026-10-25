import { strict as assert } from "node:assert";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { createServer } from "vite";

test("shared speaker headings keep every source fragment's text and precise interval visible in order", async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { TranscriptViewer } = await server.ssrLoadModule("/src/components/transcript/TranscriptViewer.tsx");
    const { AuthProvider } = await server.ssrLoadModule("/src/lib/auth.tsx");
    const { ToastProvider } = await server.ssrLoadModule("/src/components/ui.tsx");
    const spans = [["34", 1.84, 9.6], ["34", 10.3, 12.73], ["35", 13.1, 16.56],
      ["34", 18.15, 20.87], ["34", 21.64, 22.55], ["34", 23.4, 28.73],
      ["35", 29.5, 31.13], ["35", 31.88, 32.64]];
    const transcript = {
      id: "test", session_id: "test-session", recording_id: "test-audio", speakers: [],
      audio_available: false, warnings: [], speaker_count: 2, created_at: "2026-10-23T12:00:00Z",
      segments: spans.map(([label, start, end], sequence) => ({
        id: `part-${sequence}`, sequence, speaker_label: `SPEAKER_${label}`,
        start_seconds: start, end_seconds: end, original_text: `جزء-${sequence}`,
        edited_text: null, is_overlap: false, confidence: null,
        edited_by: null, edited_by_name: null, edited_at: null,
      })),
    };
    const original = JSON.stringify(transcript);
    const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(AuthProvider, null,
      React.createElement(ToastProvider, null,
        React.createElement(TranscriptViewer, { transcript, onChange: () => {} })))));
    assert.equal((html.match(/class="time num"/g) || []).length, 8);
    assert.equal((html.match(/class="speaker"/g) || []).length, 4);
    assert.equal((html.match(/class="small muted ltr">SPEAKER_34</g) || []).length, 0);
    assert.deepEqual([...html.matchAll(/data-speaker="([^"]+)"/g)].map(m => m[1]),
      ["SPEAKER_34", "SPEAKER_35", "SPEAKER_34", "SPEAKER_35"]);
    assert.deepEqual([...html.matchAll(/data-sequence="(\d+)"/g)].map(m => Number(m[1])), [0, 1, 2, 3, 4, 5, 6, 7]);
    assert.deepEqual([...html.matchAll(/جزء-(\d+)/g)].map(m => Number(m[1])), [0, 1, 2, 3, 4, 5, 6, 7]);
    assert.deepEqual([...html.matchAll(/class="time num">([^<]+)</g)].map(m => m[1]), [
      "00:00:01.840 - 00:00:09.600", "00:00:10.300 - 00:00:12.730",
      "00:00:13.100 - 00:00:16.560", "00:00:18.150 - 00:00:20.870",
      "00:00:21.640 - 00:00:22.550", "00:00:23.400 - 00:00:28.730",
      "00:00:29.500 - 00:00:31.130", "00:00:31.880 - 00:00:32.640",
    ]);
    assert.equal(html.includes('aria-expanded="false"'), false, "no click is required to see source parts");
    assert.equal(JSON.stringify(transcript), original, "rendering must not change report source records");
  } finally {
    await server.close();
  }
});
