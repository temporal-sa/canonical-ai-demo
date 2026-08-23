import assert from 'node:assert/strict';

import {
  shouldSimulateHotelFailure,
  simulateHotelFailureForAttempt,
} from './checkout-policy';

assert.equal(simulateHotelFailureForAttempt(1), true);
assert.equal(simulateHotelFailureForAttempt(2), false);
assert.equal(shouldSimulateHotelFailure(true, true), true);
assert.equal(shouldSimulateHotelFailure(true, false), false);
assert.equal(shouldSimulateHotelFailure(false, true), false);
