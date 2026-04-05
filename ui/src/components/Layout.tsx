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
} from "lucide-react";
import { useState } from "react";
import StatusBar from "./StatusBar";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "dashboard", shortcut: "1" },
  { to: "/strategies", icon: Code2, label: "strategies", shortcut: "2" },
  { to: "/backtest", icon: Play, label: "backtest", shortcut: "3" },
  { to: "/config", icon: Settings, label: "config", shortcut: "4" },
  { to: "/analysis", icon: BarChart3, label: "analysis", shortcut: "5" },
  { to: "/data", icon: Database, label: "data", shortcut: "6" },
  { to: "/learn", icon: BookOpen, label: "learn", shortcut: "7" },
];

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const currentPage = NAV_ITEMS.find(
    (n) => n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)
  );

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#07070c]">
      {/* ── Top bar: terminal prompt style ── */}
      <div className="h-[28px] bg-[#07070c] border-b border-[#1c1a28] flex items-center shrink-0 select-none">
        {/* Brand — Solana gradient hint */}
        <div className="flex items-center gap-1.5 pl-3 pr-4 h-full">
          <span className="text-[11px] font-bold tracking-[0.15em] text-[#9945ff]">
            mev
          </span>
          <span className="text-[11px] font-bold tracking-[0.15em] text-[#14f195]">
            kit
          </span>
        </div>

        {/* Prompt-style breadcrumb */}
        <div className="flex items-center gap-0 text-[11px]">
          <span className="text-[#14f195]">~</span>
          <span className="text-[#56516a]">/</span>
          <span className="text-[#c4b5fd]">
            {currentPage?.label ?? "dashboard"}
          </span>
          <span className="text-[#9945ff] ml-0.5 animate-pulse">▊</span>
        </div>

        <div className="flex-1" />

        {/* Shortcuts */}
        <div className="hidden md:flex items-center gap-2 pr-3 text-[9px] text-[#2a2838]">
          <span>
            <kbd className="px-1 py-0.5 border border-[#1c1a28] rounded-sm text-[#56516a]">⌘K</kbd>
          </span>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 min-h-0">
        {/* ── Sidebar ── */}
        <nav
          className={`${
            collapsed ? "w-[40px]" : "w-[136px]"
          } bg-[#07070c] border-r border-[#1c1a28] flex flex-col shrink-0 transition-all duration-100`}
        >
          <div className="flex-1 py-1.5 flex flex-col gap-px px-1">
            {NAV_ITEMS.map(({ to, icon: Icon, label, shortcut }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) => {
                  const base = "flex items-center gap-2 h-[28px] transition-colors duration-75 group";
                  const active = isActive
                    ? "text-[#14f195] bg-[#14f195]/[0.04]"
                    : "text-[#3d3856] hover:text-[#8b83a6] hover:bg-[#0e0e16]";
                  const pad = collapsed ? "justify-center px-0" : "px-2";
                  return `${base} ${active} ${pad}`;
                }}
              >
                {({ isActive }) => (
                  <>
                    {isActive && !collapsed && (
                      <span className="text-[9px] text-[#9945ff] mr-px">{">"}</span>
                    )}
                    <Icon size={14} className="shrink-0" />
                    {!collapsed && (
                      <span className="text-[10px] truncate">{label}</span>
                    )}
                    {!collapsed && (
                      <span className="ml-auto text-[9px] text-[#2a2838] font-mono">
                        {shortcut}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>

          <button
            onClick={() => setCollapsed(!collapsed)}
            className="h-[24px] flex items-center justify-center border-t border-[#1c1a28] text-[#2a2838] hover:text-[#56516a] transition-colors duration-75"
          >
            {collapsed ? <ChevronRight size={11} /> : <ChevronLeft size={11} />}
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
