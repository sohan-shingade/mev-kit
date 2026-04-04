import { useState } from "react";
import { patch } from "../../api/client";

const PARAMS = [
  { key: "min_spread_bps", label: "min_spread", suffix: "bps" },
  { key: "position_size_sol", label: "position", suffix: "SOL" },
  { key: "fee_bps", label: "fee_bps", suffix: "bps" },
];

export default function HotParams() {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({
    min_spread_bps: "15.0",
    position_size_sol: "0.01",
    fee_bps: "30.0",
  });

  const handleApply = async () => {
    const numeric: Record<string, number> = {};
    for (const [k, v] of Object.entries(values)) {
      numeric[k] = parseFloat(v);
    }
    try {
      await patch("/api/pipeline/params", numeric);
      setEditing(false);
    } catch {
      /* toast error */
    }
  };

  return (
    <div className="bg-bg-panel p-2">
      <div className="flex justify-between items-center mb-2">
        <span className="text-[10px] text-text-secondary uppercase tracking-wider">
          Hot Params
        </span>
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className="text-[10px] text-accent-indigo hover:underline"
          >
            EDIT
          </button>
        ) : (
          <button
            onClick={handleApply}
            className="text-[10px] text-accent-green hover:underline"
          >
            APPLY
          </button>
        )}
      </div>
      <div className="space-y-1">
        {PARAMS.map(({ key, label, suffix }) => (
          <div key={key} className="flex justify-between items-center text-xs">
            <span className="text-text-secondary">{label}</span>
            {editing ? (
              <input
                type="number"
                step="any"
                value={values[key]}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [key]: e.target.value }))
                }
                className="w-20 bg-bg-main border border-border rounded px-1 py-0.5 text-right font-mono text-accent-indigo text-xs"
              />
            ) : (
              <span className="font-mono text-accent-indigo">
                {values[key]} {suffix}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
