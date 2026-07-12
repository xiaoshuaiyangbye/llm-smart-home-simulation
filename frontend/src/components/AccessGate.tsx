import { FormEvent, useState } from "react";

interface AccessGateProps {
  error: string;
  isLoading: boolean;
  onSubmit: (accessToken: string) => Promise<void>;
}

export function AccessGate({ error, isLoading, onSubmit }: AccessGateProps) {
  const [accessToken, setAccessToken] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit(accessToken);
  }

  return (
    <main className="access-gate-shell">
      <form className="access-gate" onSubmit={handleSubmit}>
        <p className="eyebrow">LLM Smart Home Simulation</p>
        <h1>受保护的仿真环境</h1>
        <p>请输入部署管理员提供的访问令牌。令牌只用于建立 HTTP-only 会话，不会写入浏览器存储。</p>
        <label>
          访问令牌
          <input
            type="password"
            autoComplete="current-password"
            value={accessToken}
            onChange={(event) => setAccessToken(event.target.value)}
            disabled={isLoading}
            required
          />
        </label>
        {error && <p className="panel-notice" role="alert">{error}</p>}
        <button type="submit" disabled={isLoading || !accessToken}>{isLoading ? "验证中…" : "进入仿真"}</button>
      </form>
    </main>
  );
}
