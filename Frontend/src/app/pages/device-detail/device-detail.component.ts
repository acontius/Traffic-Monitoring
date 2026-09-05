import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { DeviceService } from '../../core/services/device.service';
import { MlService } from '../../core/services/ml.service';
import { ReconstructionService } from '../../core/services/reconstruction.service';
import {
  AnomalyEvent,
  Device,
  DeviceHealth,
  ReconstructionLogEntry,
  TrafficRecord,
} from '../../core/models/models';

@Component({
  selector: 'app-device-detail',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './device-detail.component.html',
  styleUrl: './device-detail.component.scss',
})
export class DeviceDetailComponent implements OnInit {
  readonly device = signal<Device | null>(null);
  readonly history = signal<TrafficRecord[]>([]);
  readonly reconstructionLog = signal<ReconstructionLogEntry[]>([]);
  readonly health = signal<DeviceHealth | null>(null);
  readonly anomalies = signal<AnomalyEvent[]>([]);
  deviceId = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly deviceService: DeviceService,
    private readonly reconstructionService: ReconstructionService,
    private readonly mlService: MlService,
  ) {}

  ngOnInit(): void {
    this.deviceId = this.route.snapshot.paramMap.get('deviceId') || '';
    if (!this.deviceId) return;

    this.deviceService.get(this.deviceId).subscribe((device) => this.device.set(device));
    this.deviceService
      .history(this.deviceId, { limit: 100 })
      .subscribe((records) => this.history.set(records));
    this.reconstructionService
      .listLog(this.deviceId)
      .subscribe((log) => this.reconstructionLog.set(log));
    this.mlService.deviceHealth(this.deviceId).subscribe((health) => this.health.set(health));
    this.mlService
      .deviceAnomalies(this.deviceId, 50)
      .subscribe((anomalies) => this.anomalies.set(anomalies));
  }

  countsOf(record: TrafficRecord): Array<[string, number]> {
    return Object.entries(record.payload?.counts || {});
  }
}
