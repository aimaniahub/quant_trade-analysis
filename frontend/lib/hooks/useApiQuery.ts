import { useEffect } from "react";
import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

export interface ApiQueryOptions<TData>
  extends Omit<UseQueryOptions<TData, Error, TData, QueryKey>, "queryKey" | "queryFn"> {
  /** React Query v5 no longer supports onSuccess on useQuery — handled via effect. */
  onSuccess?: (data: TData) => void;
}

export function useApiQuery<TData>(
  key: QueryKey,
  queryFn: () => Promise<TData>,
  options?: ApiQueryOptions<TData>,
): UseQueryResult<TData, Error> {
  const { onSuccess, ...queryOptions } = options ?? {};

  const result = useQuery<TData, Error, TData, QueryKey>({
    queryKey: key,
    queryFn,
    ...queryOptions,
  });

  useEffect(() => {
    if (result.isSuccess && result.data !== undefined && onSuccess) {
      onSuccess(result.data);
    }
    // Only re-fire when data identity / updatedAt changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.dataUpdatedAt, result.isSuccess]);

  return result;
}
