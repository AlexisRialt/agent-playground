"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { createJob, listJobs, type JobSummary } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

const POLL_INTERVAL_MS = 3000;

export default function Home() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await listJobs();
        if (!cancelled) {
          setJobs(data.sort((a, b) => b.created_at.localeCompare(a.created_at)));
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Could not reach the agent-playground API.");
      }
    }

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await createJob(text.trim());
      setText("");
      setJobs(await listJobs());
    } catch {
      setError("Failed to submit job.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">agent-playground</h1>
      <p className="mt-1 text-sm text-gray-500">
        Submit a task for the Claude agent and watch it work.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Describe a task for the agent…"
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-transparent"
        />
        <button
          type="submit"
          disabled={submitting || !text.trim()}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </form>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <table className="mt-8 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800">
            <th className="py-2 font-medium">Task</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              className="border-b border-gray-100 dark:border-gray-900"
            >
              <td className="py-2 pr-4">
                <Link href={`/jobs/${job.id}`} className="hover:underline">
                  {job.task.length > 80 ? `${job.task.slice(0, 80)}…` : job.task}
                </Link>
              </td>
              <td className="py-2 pr-4">
                <StatusBadge status={job.status} />
              </td>
              <td className="py-2 text-gray-500">
                {new Date(job.created_at).toLocaleString()}
              </td>
            </tr>
          ))}
          {jobs.length === 0 && !error && (
            <tr>
              <td colSpan={3} className="py-6 text-center text-gray-500">
                No jobs yet — submit a task above.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </main>
  );
}
