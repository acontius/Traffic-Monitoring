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
}

export interface ReconstructionConfig {
  id: number;
  scope_type: 'default' | 'location_type' | 'device';
  scope_value: string | null;
  weights: Record<string, unknown>;
  updated_at: string;
  updated_by: string | null;
}

export interface LiveEvent {
  event: 'alert' | 'device_update';
  data: Alert | { device_id: string; status: string; latest: TrafficPayload | null };
}
