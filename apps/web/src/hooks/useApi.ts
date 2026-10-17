// Load data from the API with loading / error / retry, the same way on every page.

import { useCallback, useEffect, useState } from "react";

import type { ApiResult } from "../api/client";
import { ApiError } from "../api/client";

export interface Loaded<T> {
  result: ApiResult<T> | null; // null while loading or after an error
  error: ApiError | null;
  reload: () => void;
}

/**
 * Calls `load` now and whenever `key` changes (for example new filters).
 * A slow answer for old filters is ignored if newer filters were chosen meanwhile.
 */
export function useApi<T>(load: () => Promise<ApiResult<T>>, key: string): Loaded<T> {
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    setResult(null);
    setError(null);
    load()
      .then((answer) => current && setResult(answer))
      .catch((problem) => {
        if (current) setError(problem instanceof ApiError ? problem : new ApiError(0, String(problem)));
      });
    return () => {
      current = false;
    };
    // `load` is rebuilt on every render; `key` says when the request really changes.
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { result, error, reload };
}
