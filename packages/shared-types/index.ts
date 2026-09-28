/**
 * Shared TypeScript types for hackathon-starter
 * Used by both frontend and backend for type safety
 */

// ============================================
// FoodBridge Types (mirror backend Pydantic models)
// ============================================

export type Urgency = 'high' | 'medium' | 'low';
export type SurplusStatus = 'available' | 'allocated';
export type MatchStatus = 'completed' | 'failed' | 'timeout';
export type WorkflowStatus = 'running' | 'completed' | 'failed' | 'timeout';

export interface Restaurant {
  id: string;
  name: string;
  lat: number;
  lon: number;
  address: string;
  cuisine_types: string[];
  contact: string;
}

export interface FoodSurplus {
  id: string;
  restaurant_id: string;
  meal_count: number;
  food_type: string;
  dietary_tags: string[];
  prepared_at: string; // ISO datetime
  expires_at: string;  // ISO datetime
  temperature_c: number;
  notes: string;
  status: SurplusStatus;
  hours_remaining(): number;
}

export interface Shelter {
  id: string;
  name: string;
  lat: number;
  lon: number;
  capacity: number;
  current_occupancy: number;
  urgency: Urgency;
  food_requirements: string[];
  address: string;
}

export interface CreateSurplusRequest {
  restaurant_id: string;
  meal_count: number;
  food_type: string;
  dietary_tags: string[];
  expires_in_hours: number;
  temperature_c: number;
  notes: string;
}

export interface MatchOptions {
  max_shelters?: number;
  include_summary: boolean;
}

export interface MatchRequest {
  surplus_id?: string;
  requested_radius_km: number;
  shelter_ids?: string[];
  options: MatchOptions;
}

export interface Allocation {
  shelter_id: string;
  shelter_name: string;
  meals: number;
  distance_km: number;
  score: number;
  breakdown: Record<string, { weight: number; score: number }>;
}

export interface AgentEvent {
  workflow_id: string;
  agent: string;
  status: 'running' | 'completed' | 'failed';
  detail: string;
  timestamp: string;
}

export interface MatchResponse {
  success: boolean;
  workflow_id: string;
  workflow_status: MatchStatus;
  allocation: Allocation[];
  agent_events: AgentEvent[];
  total_allocated: number;
  unallocated: number;
  summary: string;
  summary_source: string;
  retry_count: number;
  metadata: {
    weights: Record<string, number>;
    demo_mode: boolean;
    llm_provider: string;
    requested_radius_km: number;
    max_retries: number;
    duration_ms: number;
    logistics: Record<string, unknown>;
    surplus_status?: SurplusStatus;
    surplus_remaining?: number;
  };
  error?: {
    code: string;
    message: string;
    details?: unknown[];
  };
}

// ============================================
// API Error Types
// ============================================

export interface AppError {
  error: string;
  detail?: string;
  path: string;
}

// ============================================
// Chat/Solve Types
// ============================================

export interface ChatRequest {
  message: string;
  context?: string;
}

export interface ChatResponse {
  response: string;
  model: string;
  tokens_used?: number;
}

export interface SolveRequest {
  problem: string;
  context?: string;
}

export interface SolveResponse {
  solution: string;
  steps: string[];
  confidence?: number;
}

// ============================================
// Health Check
// ============================================

export interface HealthResponse {
  status: 'ok';
  version: string;
  llm_provider: string;
  llm_model: string;
  rag_enabled: boolean;
  db_enabled: boolean;
  llm_configured: boolean;
}

// ============================================
// Utility Types
// ============================================

export type ApiResponse<T> = 
  | { success: true; data: T }
  | { success: false; error: AppError };

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};