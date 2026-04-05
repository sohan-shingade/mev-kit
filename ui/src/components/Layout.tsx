import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Play,
  Settings,
  BarChart3,
  Database,
  BookOpen,
  Code2,
  ChevronLeft,
  ChevronRight,
  Zap,
} from "lucide-react";
import { useState } from "react";
import StatusBar from "./StatusBar";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", shortcut: "1" },
  { to: "/strategies", icon: Code2, label: "Strategies", shortcut: "2" },
  { to: "/backtest", icon: Play, label: "Backtest", shortcut: "3" },
  { to: "/config", icon: Settings, label: "Config", shortcut: "4" },
  { to: "/analysis", icon: BarChart3, label: "Analysis", shortcut: "5" },
  { to: "/data", icon: Database, label: "Data", shortcut: "6" },
  { to: "/learn", icon: BookOpen, label: "Learn", shortcut: "7" },
];

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const currentPage = NAV_ITEMS.find(
    (n) => n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)
  );

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#090b10]">
      {/* ── Top bar ── */}
      <div className="h-[32px] bg-[#070910] border-b border-[#141720] flex items-center shrink-0 select-none">
        {/* Brand */}
        <div className="flex items-center gap-2 px-3 border-r border-[#141720] h-full">
          <Zap size={13} className="text-accent-indigo" />
          <span className="text-[11px] font-bold tracking-wider text-text-primary">
            MEV-KIT
          </span>
        </div>

        {/* Breadcrumb */}
        <div className="flex items-center gap-1 px-3 text-[10px]">
          <span className="text-[#3a4050]">/</span>
          <span className="text-text-secondary font-medium">
            {currentPage?.label ?? "Dashboard"}
          </span>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Keyboard hints */}
        <div className="hidden md:flex items-center gap-3 px-3 text-[9px] text-[#2e3340]">
          <span>
            <kbd className="px-1 py-0.5 bg-[#141720] rounded text-[#4a5060] text-[8px]">
              ⌘K
            </kbd>{" "}
            commands
          </span>
        </div>
      </div>

      {/* ── Main body ── */}
      <div className="flex flex-1 min-h-0">
        {/* ── Sidebar ── */}
        <nav
          className={`${
            collapsed ? "w-[44px]" : "w-[140px]"
          } bg-[#070910] border-r border-[#141720] flex flex-col shrink-0 transition-all duration-150`}
        >
          {/* Nav items */}
          <div className="flex-1 py-2 flex flex-col gap-0.5 px-1.5">
            {NAV_ITEMS.map(({ to, icon: Icon, label, shortcut }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) => {
                  const base =
                    "flex items-center gap-2 rounded h-[30px] transition-all duration-100 group relative";
                  const active = isActive
                    ? "bg-accent-indigo/10 text-accent-indigo border-l-2 border-accent-indigo pl-[6px]"
                    : "text-[#4a5060] hover:text-text-secondary hover:bg-[#10131a] border-l-2 border-transparent pl-[6px]";
                  const pad = collapsed ? "justify-center px-0" : "px-1.5";
                  return `${base} ${active} ${pad}`;
                }}
              >
                <Icon size={15} className="shrink-0" />
                {!collapsed && (
                  <span className="text-[11px] font-medium truncate">
                    {label}
                  </span>
                )}
                {!collapsed && (
                  <span className="ml-auto text-[9px] text-[#2e3340] font-mono">
                    {shortcut}
                  </span>
                )}
              </NavLink>
            ))}
          </div>

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="h-[28px] flex items-center justify-center border-t border-[#141720] text-[#2e3340] hover:text-text-secondary transition-colors"
          >
            {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
          </button>
        </nav>

        {/* ── Content ── */}
        <main className="flex-1 overflow-auto bg-bg-main">
          <Outlet />
        </main>
      </div>

      {/* ── Status bar ── */}
      <StatusBar />
    </div>
  );
}
