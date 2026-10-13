# Nerva Business: reuse decisions

Reviewed 2026-10-13 against primary project documentation and licenses. This is a
source review, not a deployment benchmark or a guarantee about future licenses.
No code from these projects was copied into this increment; no new framework or
runtime dependency was added. Existing Nerva routing, MCP, workflows, HTTP policy,
encrypted storage and React UI are the integration foundation.

| Project | What is useful | Decision and commercial boundary |
| --- | --- | --- |
| [Activepieces](https://github.com/activepieces/activepieces) | Connector catalog, typed auth/action schemas, reusable pieces | Study connector patterns first. Core is MIT; `packages/ee` and server enterprise paths have separate licenses. Official embedding is Enterprise. Review each dependency before copying individual pieces. |
| [Node-RED](https://github.com/node-red/node-red) | Visual flows and a comparatively small Node runtime | Preferred candidate for a later optional workflow sidecar. Apache-2.0 core; community nodes need separate review. No sidecar is installed or integrated by this change. |
| [n8n](https://github.com/n8n-io/n8n) | Broad workflow examples; existing Nerva integrations can remain | Sustainable Use License. Current FAQ allows predefined backend workflows using customer credentials; customer creation/configuration of workflows through UI/API/MCP/AI needs a commercial agreement. Do not present its editor as our freely embeddable product. |
| [Nango](https://github.com/NangoHQ/nango) | OAuth lifecycle and token refresh | ELv2; free self-hosted scope is Auth + Proxy. Syncs, tools, webhooks and other platform features are not an unrestricted self-hosted connector platform. Defer until OAuth demand justifies the platform. |
| [Composio](https://github.com/ComposioHQ/composio) | Hosted connector breadth and MCP interface | MIT SDK does not imply an open-source backend. Optional paid supplier only after service and resale terms are settled. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Durable execution and resume patterns | MIT. Add only if a measured gap in the existing workflow runtime warrants another engine. |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Tool schemas, handoffs, tracing design | MIT. Reuse ideas without duplicating Nerva orchestration; hosted tracing must not be introduced into local-only flows. |
| [LiteLLM](https://github.com/BerriAI/litellm) | Model gateway and usage normalization | Core MIT, enterprise exceptions. Possible later gateway; existing HybridRouter handles this pilot. |
| [Dify](https://github.com/langgenius/dify) | Knowledge applications and workflow UX | Modified Apache license with multi-tenant and branding conditions; do not embed as an unrestricted white-label SaaS. |
| [Open WebUI](https://github.com/open-webui/open-webui) | Chat UX | Current branding conditions and limited exceptions require review. Keep the existing Nerva HUD. |
| [MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk) | Standard tool/connector boundary | Nerva already implements MCP in Python. No reason to add a second SDK merely to connect projects. Review the precise SDK version license before vendoring. |

## Primary license and integration references

- Activepieces [core license](https://github.com/activepieces/activepieces/blob/main/LICENSE), [enterprise license](https://github.com/activepieces/activepieces/blob/main/packages/ee/LICENSE), [embedding feature](https://github.com/activepieces/activepieces/blob/main/docs/_snippets/embed-feature.mdx), [deployment stack](https://github.com/activepieces/activepieces/blob/main/docker-compose.yml). Observed revision prefix: `b5e7818f`.
- Node-RED [license](https://github.com/node-red/node-red/blob/master/LICENSE), [runtime embedding](https://nodered.org/docs/user-guide/runtime/embedding), [container images](https://github.com/node-red/node-red-docker).
- n8n [license](https://github.com/n8n-io/n8n/blob/master/LICENSE.md), [license FAQ](https://github.com/n8n-io/n8n-docs/blob/main/docs/n8n-community-license/license-faq.md). Observed repository revision prefix: `6924027e`.
- Nango [license](https://github.com/NangoHQ/nango/blob/master/LICENSE), [self-hosting scope](https://github.com/NangoHQ/nango/blob/master/docs/guides/platform/self-hosting/self-hosting.mdx). Observed revision prefix: `41995da9`.
- Composio [license](https://github.com/ComposioHQ/composio/blob/master/LICENSE), [service terms](https://composio.dev/terms). Observed revision prefix: `808c1fc4`.
- [LangGraph license](https://github.com/langchain-ai/langgraph/blob/main/LICENSE), [Agents SDK license](https://github.com/openai/openai-agents-python/blob/main/LICENSE), [LiteLLM license](https://github.com/BerriAI/litellm/blob/main/LICENSE) and [enterprise license](https://github.com/BerriAI/litellm/blob/main/enterprise/LICENSE.md).
- [Dify license](https://github.com/langgenius/dify/blob/main/LICENSE), [Open WebUI license](https://github.com/open-webui/open-webui/blob/main/LICENSE), [MCP TypeScript license](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/LICENSE).

## Applied architecture

The first increment ships bounded native WooCommerce/HubSpot readers and CSV
imports behind the same credential, normalized-snapshot and report interfaces.
This supplies the ecommerce and automotive starting points without an additional
workflow database, worker cluster or hosted connector bill. MCP remains the
extension seam for tools; transactional writes, scheduled flows and more SaaS
connectors remain explicit follow-up work. Industry templates currently select
profile metadata; they do not install department agents or automation bundles.
