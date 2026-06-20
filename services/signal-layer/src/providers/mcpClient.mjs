let nextId = 1;

export class McpClient {
  constructor({ mcpUrl, timeoutMs = 8000 }) {
    this.mcpUrl = mcpUrl;
    this.timeoutMs = timeoutMs;
  }

  async callTool(name, args = {}) {
    return this.#post({
      jsonrpc: '2.0',
      id: nextId++,
      method: 'tools/call',
      params: { name, arguments: args }
    });
  }

  async readResource(uri) {
    return this.#post({
      jsonrpc: '2.0',
      id: nextId++,
      method: 'resources/read',
      params: { uri }
    });
  }

  async listTools() {
    return this.#post({
      jsonrpc: '2.0',
      id: nextId++,
      method: 'tools/list',
      params: {}
    });
  }

  async #post(payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(this.mcpUrl, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const text = await response.text();
      let json;
      try {
        json = text ? JSON.parse(text) : {};
      } catch {
        const error = new Error(`MCP returned non-JSON response: ${text.slice(0, 160)}`);
        error.code = 'invalid_mcp_response';
        error.retryable = false;
        throw error;
      }
      if (!response.ok) {
        const error = new Error(`MCP HTTP ${response.status}`);
        error.code = 'mcp_http_error';
        error.status = response.status;
        error.body = json;
        error.retryable = response.status >= 500 || response.status === 429;
        throw error;
      }
      if (json.error) {
        const error = new Error(json.error.message || 'MCP JSON-RPC error');
        error.code = json.error.code || 'mcp_jsonrpc_error';
        error.body = json.error;
        error.retryable = true;
        throw error;
      }
      return json.result ?? json;
    } finally {
      clearTimeout(timer);
    }
  }
}
