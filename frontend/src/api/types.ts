// API types mirrored from backend Pydantic schemas.

export interface UserRead {
  id: string;
  email: string;
  full_name: string;
  status: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: UserRead;
}

export interface ToolInfo {
  name: string;
  label: string;
  description: string;
  category: "knowledge" | "support" | "action";
  parameters_json_schema: Record<string, unknown>;
}

export interface AgentRead {
  id: string;
  name: string;
  slug: string;
  description: string;
  instructions: string;
  model: string | null;
  kind: "router" | "specialist";
  expose_as_tool: boolean;
  enabled: boolean;
  tools: string[];
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface StepRecord {
  tool: string;
  args?: Record<string, unknown> | null;
  result_preview?: string;
  duration_ms?: number;
  nested_steps?: StepRecord[] | null;
}

export interface ChatSessionRead {
  id: string;
  title: string;
  channel: string;
  agent_id: string | null;
  handoff_state: "bot" | "pending_human" | "human";
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageRead {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "human_agent" | "system";
  content: string;
  steps: StepRecord[] | null;
  usage: { input_tokens: number; output_tokens: number } | null;
  created_at: string;
  feedback: { rating: "up" | "down"; comment: string | null } | null;
}

export interface IntegrationCatalogItem {
  type: string;
  name: string;
  description: string;
  available: boolean;
}

export interface TelegramIntegration {
  id: string;
  bot_username: string;
  status: "connected" | "disconnected" | "error";
  support_chat_id: number | null;
  created_at: string;
}

export interface TelegramLink {
  code: string;
  deep_link_url: string;
  linked: boolean;
}

export interface GoldenItem {
  id: string;
  question: string;
  locale: string;
  category: string;
  difficulty: string;
  expected_answer: string;
  expected_facts: string[];
  gold_source_urls: string[];
  expected_route: string | null;
  expected_tools: string[];
  provenance: string;
  reviewed_by: string | null;
  source_message_id: string | null;
  archived: boolean;
  created_at: string;
}

export interface EvalRun {
  id: string;
  name: string;
  layer: string;
  status: string;
  config: Record<string, unknown>;
  metrics: Record<string, number>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}
