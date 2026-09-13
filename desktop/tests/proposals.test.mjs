// SPDX-License-Identifier: GPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { Proposals } from "../electron/proposals.mjs";
function fixture() {
  let config = { dpi: 1600 };
  const writes = [];
  const bridge = {
    request: async (op, args) => {
      if (op === "config-get") return structuredClone(config);
      if (op === "config-validate") {
        if (!Number.isInteger(args[0].dpi)) throw new Error("invalid");
        return args[0];
      }
      if (op === "config-save-expected") {
        assert.deepEqual(config, args[1]);
        config = args[0];
        writes.push(config);
        return config;
      }
      throw new Error(op);
    },
  };
  return {
    proposals: new Proposals(bridge),
    writes,
    change: (value) => (config = value),
  };
}
test("proposal does not write until explicit application", async () => {
  const { proposals, writes } = fixture();
  await proposals.read();
  const proposal = await proposals.propose({
    summary: "800 DPI",
    configJson: '{"dpi":800}',
  });
  assert.equal(writes.length, 0);
  assert.equal(proposal.before.dpi, 1600);
  await proposals.apply(proposal.id);
  assert.equal(writes[0].dpi, 800);
  await assert.rejects(proposals.apply(proposal.id));
});
test("stale proposals cannot overwrite newer settings", async () => {
  const { proposals, writes, change } = fixture();
  await proposals.read();
  const proposal = await proposals.propose({
    summary: "800",
    configJson: '{"dpi":800}',
  });
  change({ dpi: 3200 });
  await assert.rejects(proposals.apply(proposal.id));
  assert.equal(writes.length, 0);
});
test("invalid proposal is rejected before display", async () => {
  const { proposals } = fixture();
  await proposals.read();
  await assert.rejects(
    proposals.propose({ summary: "bad", configJson: '{"dpi":"invalid"}' }),
  );
  assert.equal(proposals.items.size, 0);
});
