export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface JobSummary {
  id: string;
  status: JobStatus;
  task: string;
  created_at: string;
  updated_at: string;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  output: string;
  is_error: boolean;
  at: string;
}

export interface Job extends JobSummary {
  log: string[];
  tool_calls: ToolCall[];
  result: string | null;
  error: string | null;
}

export interface CreateJobResponse {
  id: string;
  status: JobStatus;
}

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);

  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export function listJobs(): Promise<JobSummary[]> {
  return apiFetch<JobSummary[]>("/jobs");
}

export function getJob(id: string): Promise<Job> {
  return apiFetch<Job>(`/jobs/${encodeURIComponent(id)}`);
}

export function createJob(text: string): Promise<CreateJobResponse> {
  return apiFetch<CreateJobResponse>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
