import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Play,
  Settings,
  BarChart3,
  Database,
  BookOpen,
  Code2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { PipelineStatus } from "../api/types";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/strategies", icon: Code2, label: "Strategies" },
  { to: "/backtest", icon: Play, label: "Backtest" },
  { to: "/config", icon: Settings, label: "Config" },
  { to: "/analysis", icon: BarChart3, label: "Analysis" },
  { to: "/data", icon: Database, label: "Data" },
  { to: "/learn", icon: BookOpen, label: "Learn" },
];

export default function Layout() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const s = await get<PipelineStatus>("/api/pipeline/status");
        setStatus(s);
      } catch {
        /* server not ready */
      }
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const stateColor =
    status?.state === "running" ? "bg-accent-green" : "bg-text-secondary";

  return (
    <div className="flex h-screen overflow-hidden">
      <nav className="w-[52px] bg-bg-sidebar flex flex-col items-center py-3 gap-3 border-r border-border shrink-0">
        <div className="w-7 h-7 bg-accent-indigo rounded-md flex items-center justify-center text-xs font-bold text-white mb-2">
          M
        </div>
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            title={label}
            className={({ isActive }) =>
              `w-8 h-8 rounded-md flex items-center justify-center transition-colors ${
                isActive
                  ? "bg-bg-active text-text-primary"
                  : "text-text-secondary hover:text-text-primary hover:bg-bg-active/50"
              }`
            }
          >
            <Icon size={18} />
          </NavLink>
        ))}
        <div className="mt-auto mb-2" title={status?.state ?? "idle"}>
          <div className={`w-2.5 h-2.5 rounded-full ${stateColor}`} />
        </div>
      </nav>
      <main className="flex-1 overflow-auto bg-bg-main">
        <Outlet />
      </main>
    </div>
  );
}
