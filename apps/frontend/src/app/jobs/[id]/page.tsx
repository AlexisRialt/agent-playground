"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { getJob, type Job } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

const POLL_INTERVAL_MS = 2000;
const ACTIVE_STATUSES = new Set(["pending", "running"]);

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    async function poll() {
      try {
        const data = await getJob(params.id);
        if (cancelled) return;
        setJob(data);
        setError(null);
        if (!ACTIVE_STATUSES.has(data.status) && interval) {
          clearInterval(interval);
          interval = null;
        }
      } catch {
        if (!cancelled) setError("Job not found or the API is unreachable.");
      }
    }

    poll();
    interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [params.id]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link href="/" className="text-sm text-gray-500 hover:underline">
        ← All jobs
      </Link>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {job && (
        <>
          <div className="mt-4 flex items-center gap-3">
            <h1 className="text-lg font-semibold">{job.task}</h1>
            <StatusBadge status={job.status} />
          </div>
          <p className="mt-1 text-xs text-gray-500">
            id {job.id} · created {new Date(job.created_at).toLocaleString()} ·
            updated {new Date(job.updated_at).toLocaleString()}
          </p>

          {job.log.length > 0 && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-gray-500">Plan / log</h2>
              <div className="mt-2 space-y-2">
                {job.log.map((entry, i) => (
                  <pre
                    key={i}
                    className="whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-xs dark:border-gray-800 dark:bg-gray-900"
                  >
                    {entry}
                  </pre>
                ))}
              </div>
            </section>
          )}

          {job.tool_calls.length > 0 && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-gray-500">Tool calls</h2>
              <div className="mt-2 space-y-2">
                {job.tool_calls.map((tc, i) => (
                  <div
                    key={i}
                    className={`rounded border p-3 text-xs ${
                      tc.is_error
                        ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950"
                        : "border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-900"
                    }`}
                  >
                    <div className="font-medium">{tc.tool}</div>
                    <pre className="mt-1 whitespace-pre-wrap">
                      {JSON.stringify(tc.input, null, 2)}
                    </pre>
                    <pre className="mt-1 whitespace-pre-wrap text-gray-600 dark:text-gray-400">
                      {tc.output}
                    </pre>
                  </div>
                ))}
              </div>
            </section>
          )}

          {job.result && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-gray-500">Result</h2>
              <pre className="mt-2 whitespace-pre-wrap rounded border border-green-200 bg-green-50 p-3 text-sm dark:border-green-900 dark:bg-green-950">
                {job.result}
              </pre>
            </section>
          )}

          {job.error && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-gray-500">Error</h2>
              <pre className="mt-2 whitespace-pre-wrap rounded border border-red-200 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950">
                {job.error}
              </pre>
            </section>
          )}
        </>
      )}
    </main>
  );
}
