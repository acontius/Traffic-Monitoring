import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface ReportFilter {
  device_id?: string;
  location_type?: string;
  date_from?: string;
  date_to?: string;
}

@Injectable({ providedIn: 'root' })
export class ReportService {
  private readonly base = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  getJson(filter: ReportFilter): Observable<unknown[]> {
    return this.http.get<unknown[]>(`${this.base}/reports`, {
      params: { ...this.cleanParams(filter), format: 'json' },
    });
  }

  downloadCsv(filter: ReportFilter): Observable<Blob> {
    return this.http.get(`${this.base}/reports`, {
      params: { ...this.cleanParams(filter), format: 'csv' },
      responseType: 'blob',
    });
  }

  private cleanParams(filter: ReportFilter): Record<string, string> {
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(filter)) {
      if (value) {
        params[key] = value;
      }
    }
    return params;
  }
}
