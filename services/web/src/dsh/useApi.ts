import { useCallback, useEffect, useState } from "react";
import { apiGet } from "./rest";

type State<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

export function useApi<T>(path: string): State<T> {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<Omit<State<T>, "reload">>({
    data: null,
    error: null,
    loading: true,
  });
  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let alive = true;
    setState({ data: null, error: null, loading: true });
    apiGet<T>(path)
      .then((data) => {
        if (alive) setState({ data, error: null, loading: false });
      })
      .catch((cause: unknown) => {
        if (alive) {
          setState({
            data: null,
            error: cause instanceof Error ? cause.message : "request failed",
            loading: false,
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [path, tick]);

  return { ...state, reload };
}
