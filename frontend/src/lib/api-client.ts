/**
 * API client placeholder — will be auto-generated from FastAPI OpenAPI schema.
 * Run `pnpm generate:api` after the backend is running to regenerate.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  version: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json() as Promise<HealthResponse>;
}

export { API_BASE_URL };
