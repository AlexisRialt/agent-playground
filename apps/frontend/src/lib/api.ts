export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  output: string;
  is_error: boolean;
  at: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  task: string;
  log: string[];
  tool_calls: ToolCall[];
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  id: string;
  status: JobStatus;
  task: string;
  created_at: string;
  updated_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function listJobs(): Promise<JobSummary[]> {
  return request<JobSummary[]>("/jobs");
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}`);
}

export function createJob(text: string): Promise<{ id: string; status: JobStatus }> {
  return request("/jobs", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}
