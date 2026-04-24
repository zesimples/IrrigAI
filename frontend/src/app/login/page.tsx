"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/ui/Logo";
import { setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";
      const res = await fetch(`${API_BASE}/auth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? "Email ou palavra-passe incorretos.");
        return;
      }
      const data = await res.json();
      setToken(data.access_token);
      router.replace("/");
    } catch {
      setError("Erro de ligação. Verifique a sua rede.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-white px-6">
      <div className="w-full max-w-sm space-y-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo size={40} />
          <p className="font-display text-[20px] font-[500] text-irrigai-text tracking-[-0.02em]">
            IrrigAI
          </p>
          <p className="text-[13px] text-irrigai-text-muted">Inicie sessão para continuar</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
          <div className="space-y-1.5">
            <label
              htmlFor="email"
              className="text-[12px] font-medium uppercase tracking-[0.06em] text-irrigai-text-hint"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@exemplo.pt"
              className="w-full rounded-xl bg-irrigai-surface px-4 py-3.5 text-[15px] text-irrigai-text placeholder-irrigai-text-muted outline-none focus:ring-2 focus:ring-irrigai-green/30"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="password"
              className="text-[12px] font-medium uppercase tracking-[0.06em] text-irrigai-text-hint"
            >
              Palavra-passe
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full rounded-xl bg-irrigai-surface px-4 py-3.5 text-[15px] text-irrigai-text placeholder-irrigai-text-muted outline-none focus:ring-2 focus:ring-irrigai-green/30"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-600"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            data-testid="login-submit"
            className="w-full rounded-xl bg-irrigai-green px-4 py-3.5 text-[15px] font-medium text-white disabled:opacity-50"
          >
            {loading ? "A entrar…" : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
