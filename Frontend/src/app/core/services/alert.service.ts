import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Alert } from '../models/models';

@Injectable({ providedIn: 'root' })
export class AlertService {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  list(unacknowledgedOnly = false): Observable<Alert[]> {
    return this.http.get<Alert[]>(`${this.base}/alerts`, {
      params: { unacknowledged_only: String(unacknowledgedOnly) },
    });
  }

  acknowledge(alertId: number): Observable<Alert> {
    return this.http.post<Alert>(`${this.base}/alerts/${alertId}/acknowledge`, {});
  }
}
