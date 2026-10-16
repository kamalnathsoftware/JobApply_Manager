import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const nav = [
  ["/", "Dashboard"], ["/resumes", "Resumes"], ["/accounts", "Accounts"], ["/personal", "Personal details"],
  ["/search-profiles", "Search Profiles"], ["/schedules", "Schedules"],
  ["/review", "Review Queue"], ["/applications", "Applications"], ["/settings", "Settings"],
] as const;

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r bg-white p-4">
        <h1 className="mb-6 text-lg font-bold">JobApply Manager</h1>
        <nav className="flex flex-col gap-1">
          {nav.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => `rounded px-3 py-2 text-sm ${isActive ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-8 text-xs text-slate-500">
          <div className="truncate">{user?.email}</div>
          <button onClick={logout} className="mt-1 underline">Log out</button>
        </div>
      </aside>
      <main className="flex-1 p-6"><Outlet /></main>
    </div>
  );
}
