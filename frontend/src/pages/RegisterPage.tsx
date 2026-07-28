import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";

export default function RegisterPage() {
  const { register } = useAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await register(email, fullName, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha no cadastro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-screen items-center justify-center">
      <form
        onSubmit={onSubmit}
        className="w-96 rounded-2xl border border-line bg-surface p-8"
      >
        <h1 className="mb-1 text-xl font-semibold">⚡ Skywalker</h1>
        <p className="mb-6 text-sm text-mut">Crie sua conta</p>
        {error && (
          <div className="mb-4 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
            {error}
          </div>
        )}
        <label className="mb-3 block text-sm">
          <span className="text-mut">Nome</span>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 outline-none focus:border-faint"
          />
        </label>
        <label className="mb-3 block text-sm">
          <span className="text-mut">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 outline-none focus:border-faint"
          />
        </label>
        <label className="mb-6 block text-sm">
          <span className="text-mut">Senha (mín. 8 caracteres)</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 outline-none focus:border-faint"
          />
        </label>
        <button
          disabled={busy}
          className="w-full rounded-lg bg-clay py-2 font-medium hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Criando…" : "Criar conta"}
        </button>
        <p className="mt-4 text-center text-sm text-mut">
          Já tem conta?{" "}
          <Link to="/login" className="text-clay hover:underline">
            Entrar
          </Link>
        </p>
      </form>
    </div>
  );
}
