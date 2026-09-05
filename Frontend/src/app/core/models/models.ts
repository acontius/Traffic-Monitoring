export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Device {
  device_id: string;
  location_type: string;
  label: string | null;
  latitude: number | null;
  longitude: number | null;
  contractor: string | null;
  ip_address: string | null;
  status: string;
  expected_interval_seconds: number;
  last_seen_at: string | null;
}

export interface TrafficPayload {
  device_id: string;
  location_type: string;
  timestamp: string;
  interval_minutes?: number;
  counts: Record<string, number>;
  reconstructed?: boolean;
  manual_override?: boolean;
}

export interface TrafficRecord {
  device_id: string;
  timestamp: string;
  payload: TrafficPayload;
  is_valid: boolean;
  anomaly_flag: boolean;
  anomaly_reason?: string | null;
  is_reconstructed: boolean;
}

export interface Alert {
  id: number;
  type: string;
  device_id: string | null;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  details: unknown;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

export interface ForwardingLogEntry {
  id: number;
  device_id: string;
  timestamp: string;
  status: 'pending' | 'sent' | 'failed' | 'dead_letter';
  attempt_count: number;
  last_attempt_at: string | null;
  response_code: number | null;
  response_body: string | null;
}

export interface ReconstructionLogEntry {
  id: number;
  device_id: string;
  timestamp: string;
  method: string;
  formula_snapshot: unknown;
  inputs: unknown;
  manual_override: boolean;
  created_by: string | null;
  created_at: string;
  confidence?: number | null;
  reconstruction_level?: string | null;
  model_version?: string | null;
  review_status?: 'auto' | 'pending_review' | 'accepted' | 'rejected' | 'edited';
}

export interface ReconstructionConfig {
  id: number;
  scope_type: 'default' | 'location_type' | 'device';
  scope_value: string | null;
  weights: Record<string, unknown>;
  updated_at: string;
  updated_by: string | null;
}

export interface DeviceHealth {
  device_id: string;
  health_status: 'HEALTHY' | 'DEGRADED' | 'SUSPICIOUS' | 'OFFLINE' | 'RECOVERING';
  snapshot_at: string | null;
  signals: Record<string, unknown>;
}

export interface AnomalyEvent {
  id: number;
  device_id: string;
  timestamp: string;
  anomaly_type: string;
  severity: 'info' | 'warning' | 'critical';
  score: number;
  observed: unknown;
  expected: unknown;
  evidence: unknown;
  status: string;
  created_at: string;
}

export interface MlModel {
  id: number;
  model_name: string;
  model_version: string;
  model_type: string;
  trained_at: string;
  training_data_range_start: string | null;
  training_data_range_end: string | null;
  feature_version: string;
  metrics: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface TrafficEvent {
  id: number;
  name: string;
  event_type: string;
  start_at: string;
  end_at: string;
  impact_scope: Record<string, unknown> | null;
  description: string | null;
  created_by: string | null;
  created_at: string;
}

export interface LiveEvent {
  event: 'alert' | 'device_update' | 'anomaly_detected' | 'reconstruction_completed' | 'device_health_changed';
  data:
    | Alert
    | { device_id: string; status: string; latest: TrafficPayload | null }
    | { device_id: string; timestamp: string; severity: string; score: number; anomaly_type: string }
    | { device_id: string; timestamp: string; method: string; confidence: number | null; review_status: string }
    | { device_id: string; health_status: string; signals: Record<string, unknown> };
}
