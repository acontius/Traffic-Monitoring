import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ForwardingLogEntry, ReconstructionConfig, ReconstructionLogEntry } from '../models/models';

@Injectable({ providedIn: 'root' })
export class ReconstructionService {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  listConfig(): Observable<ReconstructionConfig[]> {
    return this.http.get<ReconstructionConfig[]>(`${this.base}/reconstruction/config`);
  }

  upsertConfig(
    body: Pick<ReconstructionConfig, 'scope_type' | 'scope_value' | 'weights'>,
  ): Observable<ReconstructionConfig> {
    return this.http.put<ReconstructionConfig>(`${this.base}/reconstruction/config`, body);
  }

  listLog(deviceId?: string): Observable<ReconstructionLogEntry[]> {
    return this.http.get<ReconstructionLogEntry[]>(`${this.base}/reconstruction/log`, {
      params: deviceId ? { device_id: deviceId } : {},
    });
  }

  listForwarding(status?: string): Observable<ForwardingLogEntry[]> {
    return this.http.get<ForwardingLogEntry[]>(`${this.base}/forwarding`, {
      params: status ? { status } : {},
    });
  }

  resendForwarding(id: number): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.base}/forwarding/${id}/resend`, {});
  }
}
