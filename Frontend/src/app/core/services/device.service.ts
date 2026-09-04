import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Device, TrafficRecord } from '../models/models';

@Injectable({ providedIn: 'root' })
export class DeviceService {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  list(): Observable<Device[]> {
    return this.http.get<Device[]>(`${this.base}/devices`);
  }

  get(deviceId: string): Observable<Device> {
    return this.http.get<Device>(`${this.base}/devices/${deviceId}`);
  }

  latestAll(): Observable<TrafficRecord[]> {
    return this.http.get<TrafficRecord[]>(`${this.base}/records/latest`);
  }

  history(
    deviceId: string,
    params: { date_from?: string; date_to?: string; limit?: number } = {},
  ): Observable<TrafficRecord[]> {
    return this.http.get<TrafficRecord[]>(`${this.base}/records/${deviceId}/history`, {
      params: params as Record<string, string>,
    });
  }

  manualOverride(body: {
    device_id: string;
    timestamp: string;
    counts: Record<string, number>;
    reason?: string;
  }): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.base}/records/manual-override`, body);
  }
}
