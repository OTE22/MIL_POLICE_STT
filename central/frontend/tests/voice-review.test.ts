import { strict as assert } from 'node:assert';
import { comparisonScore, printExplanation } from '../src/lib/voice-review';
import type { BiometricCheck, BiometricPrintCheck } from '../src/api/types';
const result = { total_active_prints: 3, coherence_threshold: 0.65, near_duplicate_threshold: 0.98,
  groups: [{ pairs: [{ first_id: 'a', second_id: 'b', similarity: 0.83 }] }, { pairs: [] }] } as unknown as BiometricCheck;
assert.equal(comparisonScore(result, 'a', 'b'), 0.83);
assert.equal(comparisonScore(result, 'b', 'a'), 0.83);
assert.equal(comparisonScore(result, 'a', 'c'), null);
assert.equal(comparisonScore(result, 'a', 'a'), null);
assert.match(printExplanation({ status: 'SINGLE_PRINT' } as BiometricPrintCheck, result), /متوافقة/);
assert.match(printExplanation({ status: 'ISOLATED' } as BiometricPrintCheck, result), /0.65/);
assert.match(printExplanation({ status: 'NEAR_DUPLICATE' } as BiometricPrintCheck, result), /0.98/);
console.log('Voice review: compatible comparisons and actionable explanations passed.');
