import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

export interface ApiQueryOptions<TData>
  extends Omit<UseQueryOptions<TData, Error, TData, QueryKey>, "queryKey" | "queryFn"> {
  onSuccess?: (data: TData) => void;
}

export function useApiQuery<TData>(
  key: QueryKey,
  queryFn: () => Promise<TData>,
  options?: ApiQueryOptions<TData>,
): UseQueryResult<TData, Error> {
  return useQuery<TData, Error, TData, QueryKey>({
    queryKey: key,
    queryFn,
    ...options,
  });
}
