import { useEffect, useState } from "react";
import { apiGet } from "./rest";

type State<T> = { data: T | null; error: string | null; loading: boolean };

export function useApi<T>(path: string): State<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });

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
  }, [path]);

  return state;
}
