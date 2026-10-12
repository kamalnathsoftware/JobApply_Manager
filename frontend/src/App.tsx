import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./hooks/useAuth";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-6">Loading…</p>;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

const pages: [string, string][] = [
  ["resumes", "Resumes"], ["accounts", "Accounts"], ["search-profiles", "Search Profiles"],
  ["schedules", "Schedules"], ["review", "Review Queue"], ["applications", "Applications"],
  ["settings", "Settings"],
];

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login mode="login" />} />
      <Route path="/register" element={<Login mode="register" />} />
      <Route element={<Protected />}>
        <Route index element={<Placeholder title="Dashboard" />} />
        {pages.map(([p, t]) => <Route key={p} path={p} element={<Placeholder title={t} />} />)}
      </Route>
    </Routes>
  );
}
