import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./hooks/useAuth";
import Accounts from "./pages/Accounts";
import Applications from "./pages/Applications";
import Dashboard from "./pages/Dashboard";
import Personal from "./pages/Personal";
import Login from "./pages/Login";
import Resumes from "./pages/Resumes";
import ReviewQueue from "./pages/ReviewQueue";
import Schedules from "./pages/Schedules";
import SearchProfiles from "./pages/SearchProfiles";
import Settings from "./pages/Settings";

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-6">Loading…</p>;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login mode="login" />} />
      <Route path="/register" element={<Login mode="register" />} />
      <Route element={<Protected />}>
        <Route index element={<Dashboard />} />
        <Route path="resumes" element={<Resumes />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="search-profiles" element={<SearchProfiles />} />
        <Route path="schedules" element={<Schedules />} />
        <Route path="review" element={<ReviewQueue />} />
        <Route path="applications" element={<Applications />} />
        <Route path="personal" element={<Personal />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
