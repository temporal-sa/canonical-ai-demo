export function simulateHotelFailureForAttempt(attempt: number): boolean {
  return attempt === 1;
}

export function shouldSimulateHotelFailure(enabled: boolean, requestedForAttempt: boolean): boolean {
  return enabled && requestedForAttempt;
}
