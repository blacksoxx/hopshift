import { ApiError } from "@/api";

export interface ErrorInfo {
  title: string;
  message: string;
  status?: number;
}

/** A title and message for an API failure, keyed on the status codes the connections API uses. */
export function describeApiError(exc: unknown): ErrorInfo {
  if (exc instanceof ApiError) {
    const title =
      exc.status === 409
        ? "That name is already in use"
        : exc.status === 503
          ? "Secrets cannot be stored"
          : exc.status === 400
            ? "The configuration was rejected"
            : exc.status === 404
              ? "Not found"
              : exc.status === 403
                ? "Not allowed"
                : "Request failed";
    return { title, message: exc.message, status: exc.status };
  }
  return { title: "Request failed", message: (exc as Error | undefined)?.message || "Unknown error" };
}
