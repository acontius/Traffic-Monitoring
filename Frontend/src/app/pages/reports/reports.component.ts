import { CommonModule } from '@angular/common';
import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DeviceService } from '../../core/services/device.service';
import { ReportFilter, ReportService } from '../../core/services/report.service';
import { Device, TrafficRecord } from '../../core/models/models';

@Component({
    selector: 'app-reports',
    imports: [CommonModule, FormsModule],
    templateUrl: './reports.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrl: './reports.component.scss'
})
export class ReportsComponent {
  readonly devices = signal<Device[]>([]);
  readonly rows = signal<Partial<TrafficRecord>[]>([]);
  readonly loading = signal(false);

  filter: ReportFilter = {};

  constructor(
    private readonly deviceService: DeviceService,
    private readonly reportService: ReportService,
  ) {
    this.deviceService.list().subscribe((devices) => this.devices.set(devices));
  }

  runReport(): void {
    this.loading.set(true);
    this.reportService.getJson(this.filter).subscribe({
      next: (rows) => {
        this.rows.set(rows as Partial<TrafficRecord>[]);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  downloadCsv(): void {
    this.reportService.downloadCsv(this.filter).subscribe((blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'traffic_report.csv';
      link.click();
      URL.revokeObjectURL(url);
    });
  }
}
