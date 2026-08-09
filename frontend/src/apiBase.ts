// Shared API origin. Override it at build/dev time with VITE_API_BASE.
// Override with VITE_API_BASE at build/dev time.
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.DEV ? "http://localhost:8000" : "");
