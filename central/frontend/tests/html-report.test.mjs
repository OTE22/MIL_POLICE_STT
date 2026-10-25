import { strict as assert } from "node:assert";
import { test } from "node:test";
import { createServer } from "vite";

test("report payload strips server-owned snapshots and preserves source references and wording", async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const lib = await server.ssrLoadModule("/src/lib/html-report.ts");
    const first = lib.newStatement();
    first.values.statement_name = "Participant";
    first.person_snapshot = { values: { statement_name: "Server snapshot" } };
    first.entries = [{ ...lib.newEntry(), question: "Where?", answer: "At home", source_block_ids: ["qa-source"], source_snapshot: [{ block_id: "forged" }] }];
    const second = lib.newStatement();
    const note = lib.newNote();
    assert.notEqual(first.id, second.id);
    assert.equal(second.values.statement_name, undefined);
    const document = { revision: "statement-html-1", subject: "Report", investigator_id: null, blocks: [note, first, second] };
    const payload = lib.editableDocument(document);
    assert.equal(payload.blocks[1].person_snapshot, undefined);
    assert.equal(payload.blocks[1].entries[0].source_snapshot, undefined);
    assert.deepEqual(payload.blocks[1].entries[0].source_block_ids, ["qa-source"]);
    assert.equal(payload.blocks[1].entries[0].answer, "At home");
    assert.deepEqual(payload.blocks.map(block => block.id), [note.id, first.id, second.id]);
    assert.equal(payload.blocks[0].entries, undefined);
    assert.ok(first.person_snapshot, "serialization must not mutate the local saved snapshot");
  } finally { await server.close(); }
});
