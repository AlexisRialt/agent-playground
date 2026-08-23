import type { JobStatus } from "@/lib/api";

const COLORS: Record<JobStatus, string> = {
  pending: "bg-amber-100 text-amber-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

export default function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${COLORS[status]}`}
    >
      {status}
    </span>
  );
}
