import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  AnomalyEvent,
  DeviceHealth,
  MlModel,
  ReconstructionLogEntry,
  TrafficEvent,
} from '../models/models';

@Injectable({ providedIn: 'root' })
export class MlService {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  deviceHealth(deviceId: string): Observable<DeviceHealth> {
    return this.http.get<DeviceHealth>(`${this.base}/ml/devices/${deviceId}/health`);
  }

  deviceAnomalies(deviceId: string, limit = 200): Observable<AnomalyEvent[]> {
    return this.http.get<AnomalyEvent[]>(`${this.base}/ml/devices/${deviceId}/anomalies`, {
      params: { limit },
    });
  }

  deviceReconstructions(deviceId: string, limit = 200): Observable<ReconstructionLogEntry[]> {
    return this.http.get<ReconstructionLogEntry[]>(
      `${this.base}/ml/devices/${deviceId}/reconstructions`,
      { params: { limit } },
    );
  }

  models(): Observable<MlModel[]> {
    return this.http.get<MlModel[]>(`${this.base}/ml/models`);
  }

  metrics(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`${this.base}/ml/metrics`);
  }

  trafficEvents(): Observable<TrafficEvent[]> {
    return this.http.get<TrafficEvent[]>(`${this.base}/traffic-events`);
  }

  createTrafficEvent(body: {
    name: string;
    event_type: string;
    start_at: string;
    end_at: string;
    description?: string;
  }): Observable<TrafficEvent> {
    return this.http.post<TrafficEvent>(`${this.base}/traffic-events`, body);
  }
}
