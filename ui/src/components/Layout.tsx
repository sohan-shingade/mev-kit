import { Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <div className="flex h-screen">
      <nav className="w-[52px] bg-bg-sidebar border-r border-border shrink-0" />
      <main className="flex-1 overflow-auto bg-bg-main">
        <Outlet />
      </main>
    </div>
  );
}
