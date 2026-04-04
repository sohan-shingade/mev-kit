import { useState } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";

export interface Column {
  key: string;
  label: string;
}

interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

interface DataTableProps {
  columns: Column[];
  data: Record<string, unknown>[];
  sortable?: boolean;
  pagination?: PaginationProps;
}

function renderCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export default function DataTable({
  columns,
  data,
  sortable = false,
  pagination,
}: DataTableProps) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  function handleSort(key: string) {
    if (!sortable) return;
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sorted = sortKey
    ? [...data].sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av ?? "").localeCompare(String(bv ?? ""));
        return sortDir === "asc" ? cmp : -cmp;
      })
    : data;

  return (
    <div className="flex flex-col gap-0">
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border">
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`text-left px-2 py-1.5 text-text-secondary uppercase tracking-wider text-[10px] font-medium ${
                    sortable ? "cursor-pointer select-none hover:text-text-primary" : ""
                  }`}
                >
                  <span className="flex items-center gap-0.5">
                    {col.label}
                    {sortable && sortKey === col.key && (
                      sortDir === "asc"
                        ? <ChevronUp size={10} />
                        : <ChevronDown size={10} />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="text-center py-6 text-text-secondary"
                >
                  No data
                </td>
              </tr>
            ) : (
              sorted.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-border/40 hover:bg-bg-panel/50 transition-colors"
                >
                  {columns.map((col) => (
                    <td key={col.key} className="px-2 py-1 font-mono text-text-primary">
                      {renderCell(row[col.key])}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {pagination && pagination.totalPages > 1 && (
        <div className="flex items-center justify-between px-2 py-1.5 border-t border-border bg-bg-panel/30">
          <span className="text-[10px] text-text-secondary">
            Page {pagination.page} of {pagination.totalPages}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => pagination.onPageChange(pagination.page - 1)}
              disabled={pagination.page <= 1}
              className="px-2 py-0.5 text-xs bg-bg-panel border border-border rounded disabled:opacity-40 hover:bg-bg-active transition-colors"
            >
              Prev
            </button>
            <button
              onClick={() => pagination.onPageChange(pagination.page + 1)}
              disabled={pagination.page >= pagination.totalPages}
              className="px-2 py-0.5 text-xs bg-bg-panel border border-border rounded disabled:opacity-40 hover:bg-bg-active transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
