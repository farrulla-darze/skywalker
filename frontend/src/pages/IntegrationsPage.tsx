import { QRCodeSVG } from "qrcode.react";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  IntegrationCatalogItem,
  TelegramIntegration,
  TelegramLink,
} from "../api/types";

export default function IntegrationsPage() {
  const [catalog, setCatalog] = useState<IntegrationCatalogItem[]>([]);
  const [telegram, setTelegram] = useState<TelegramIntegration | null>(null);
  const [pairing, setPairing] = useState<TelegramLink | null>(null);
  const [botToken, setBotToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setCatalog(await api<IntegrationCatalogItem[]>("/api/v1/integrations/catalog"));
    setTelegram(await api<TelegramIntegration | null>("/api/v1/integrations/telegram"));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function connect() {
    setError(null);
    setBusy(true);
    try {
      await api("/api/v1/integrations/telegram/connect", {
        method: "POST",
        body: { bot_token: botToken },
      });
      setBotToken("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao conectar");
    } finally {
      setBusy(false);
    }
  }

  async function showPairing() {
    setError(null);
    try {
      setPairing(await api<TelegramLink>("/api/v1/integrations/telegram/pairing-link"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao gerar link");
    }
  }

  async function disconnect() {
    if (!confirm("Desconectar o bot do Telegram?")) return;
    await api("/api/v1/integrations/telegram", { method: "DELETE" });
    setPairing(null);
    await load();
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="text-xl font-semibold">Integrações</h1>
      <p className="mb-6 text-sm text-faint">
        Biblioteca de canais e integrações do agente.
      </p>

      {error && (
        <div className="mb-4 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {catalog.map((item) => (
          <div
            key={item.type}
            className={`rounded-xl border p-5 ${
              item.available
                ? "border-line bg-surface"
                : "border-line bg-surface opacity-60"
            }`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="text-2xl">{item.type === "telegram" ? "📨" : "💼"}</span>
              <span className="font-medium">{item.name}</span>
              {!item.available && (
                <span className="ml-auto rounded bg-raised px-2 py-0.5 text-[10px] uppercase text-faint">
                  em breve
                </span>
              )}
              {item.type === "telegram" && telegram?.status === "connected" && (
                <span className="ml-auto rounded bg-ok/15 px-2 py-0.5 text-[10px] uppercase text-ok">
                  conectado
                </span>
              )}
            </div>
            <p className="text-sm text-faint">{item.description}</p>

            {item.type === "telegram" && (
              <div className="mt-4 border-t border-line pt-4">
                {!telegram ? (
                  <div>
                    <label className="text-xs text-mut">
                      Token do bot (crie em @BotFather)
                    </label>
                    <div className="mt-1 flex gap-2">
                      <input
                        value={botToken}
                        onChange={(e) => setBotToken(e.target.value)}
                        placeholder="123456:ABC-DEF..."
                        className="flex-1 rounded-lg border border-line bg-raised px-3 py-2 text-sm"
                      />
                      <button
                        disabled={busy || botToken.length < 20}
                        onClick={() => void connect()}
                        className="rounded-lg bg-clay px-4 text-sm font-medium hover:opacity-90 disabled:opacity-40"
                      >
                        {busy ? "…" : "Conectar"}
                      </button>
                    </div>
                    <p className="mt-2 text-xs text-faint">
                      Requer PUBLIC_BASE_URL acessível pela internet para o webhook
                      (ex.: túnel ngrok/cloudflared em dev).
                    </p>
                  </div>
                ) : (
                  <div className="text-sm">
                    <div className="mb-3 text-mut">
                      Bot: <span className="text-fg">@{telegram.bot_username}</span>
                      {telegram.support_chat_id ? (
                        <span className="ml-2 text-ok">
                          · escalação ativa
                        </span>
                      ) : (
                        <span className="ml-2 text-warn">
                          · envie /support_here no chat que receberá escalações
                        </span>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => void showPairing()}
                        className="rounded-lg bg-clay px-3 py-1.5 text-sm hover:opacity-90"
                      >
                        📱 Parear meu Telegram
                      </button>
                      <button
                        onClick={() => void disconnect()}
                        className="rounded-lg bg-raised px-3 py-1.5 text-sm text-mut hover:bg-hover"
                      >
                        Desconectar
                      </button>
                    </div>
                    {pairing && (
                      <div className="mt-4 flex items-center gap-4 rounded-lg border border-line bg-white p-4">
                        <QRCodeSVG value={pairing.deep_link_url} size={140} />
                        <div className="text-zinc-900">
                          <div className="font-medium">
                            Escaneie com o celular
                          </div>
                          <div className="mt-1 text-xs text-faint">
                            Abre o Telegram no bot e envia /start com o seu
                            código de pareamento. Depois é só conversar com o
                            agente — de verdade, no seu celular.
                          </div>
                          <a
                            href={pairing.deep_link_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-2 inline-block text-xs text-indigo-600 underline"
                          >
                            {pairing.deep_link_url}
                          </a>
                          {pairing.linked && (
                            <div className="mt-1 text-xs font-medium text-emerald-600">
                              ✓ já pareado
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
