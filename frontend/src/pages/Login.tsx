import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login, register } from "../api/auth";
import { useAuth } from "../hooks/useAuth";

export default function Login({ mode }: { mode: "login" | "register" }) {
  const nav = useNavigate();
  const { refetch } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const isLogin = mode === "login";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      if (!isLogin) await register(email, password);
      await login(email, password);
      refetch();
      nav("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  const input = "w-full rounded border px-3 py-2";
  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border bg-white p-6 shadow-sm">
      <h1 className="mb-4 text-xl font-bold">{isLogin ? "Sign in" : "Create account"}</h1>
      <form onSubmit={submit} className="space-y-3">
        <input className={input} type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" placeholder="Password (min 8 chars)" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="w-full rounded bg-slate-900 py-2 text-white">{isLogin ? "Sign in" : "Register"}</button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        {isLogin ? <>No account? <Link className="underline" to="/register">Register</Link></> : <>Have one? <Link className="underline" to="/login">Sign in</Link></>}
      </p>
    </div>
  );
}
