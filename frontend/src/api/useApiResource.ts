import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: unknown };

export type ApiResource<T> = {
  state: AsyncState<T>;
  reload: () => void;
};

/**
 * Loads a backend resource with abort-on-unmount and an explicit reload.
 * `loader` must be a stable reference (module function or useCallback).
 */
export function useApiResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
): ApiResource<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    loader(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ status: "success", data });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ status: "error", error });
        }
      });

    return () => controller.abort();
  }, [loader, reloadToken]);

  const reload = useCallback(() => {
    setReloadToken((value) => value + 1);
  }, []);

  return { state, reload };
}