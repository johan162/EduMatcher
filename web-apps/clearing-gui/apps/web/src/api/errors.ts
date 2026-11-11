/**
 * The three ways a request can fail, kept distinct so a screen can say which:
 *
 * - `ApiError`: the gateway answered with its error envelope
 *   (`{"error": {"code", "message", ...}}`), e.g. `403 SCOPE_DENIED` or
 *   `503 CLEARING_DB`.
 * - `ContractError`: the gateway answered 2xx but the body does not match the
 *   released contract. Shown as an error -- never as an empty table.
 * - `NetworkError`: no answer at all (gateway down, proxy misconfigured).
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly field?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ContractError extends Error {
  constructor(
    public readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = "ContractError";
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

/** True for the refusals a user cannot fix by retrying: 403s. */
export function isForbidden(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403;
}
