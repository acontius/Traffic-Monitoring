import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DeviceService } from '../../core/services/device.service';
import { ReconstructionService } from '../../core/services/reconstruction.service';
import { Device, ForwardingLogEntry } from '../../core/models/models';

@Component({
  selector: 'app-manual-control',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './manual-control.component.html',
  styleUrl: './manual-control.component.scss',
})
export class ManualControlComponent implements OnInit {
  readonly failedForwarding = signal<ForwardingLogEntry[]>([]);
  readonly devices = signal<Device[]>([]);
  readonly overrideStatus = signal<string | null>(null);

  overrideForm = {
    device_id: '',
    timestamp: '',
    countsJson: '{"سواری": 0}',
    reason: '',
  };

  constructor(
    private readonly reconstructionService: ReconstructionService,
    private readonly deviceService: DeviceService,
  ) {}

  ngOnInit(): void {
    this.loadForwarding();
    this.deviceService.list().subscribe((devices) => this.devices.set(devices));
  }

  loadForwarding(): void {
    this.reconstructionService.listForwarding('failed').subscribe((rows) => {
      this.reconstructionService.listForwarding('dead_letter').subscribe((deadLetterRows) => {
        this.failedForwarding.set([...rows, ...deadLetterRows]);
      });
    });
  }

  resend(entry: ForwardingLogEntry): void {
    this.reconstructionService.resendForwarding(entry.id).subscribe(() => this.loadForwarding());
  }

  submitOverride(): void {
    this.overrideStatus.set(null);
    let counts: Record<string, number>;
    try {
      counts = JSON.parse(this.overrideForm.countsJson);
    } catch {
      this.overrideStatus.set('JSON شمارش‌ها نامعتبر است');
      return;
    }

    this.deviceService
      .manualOverride({
        device_id: this.overrideForm.device_id,
        timestamp: new Date(this.overrideForm.timestamp).toISOString(),
        counts,
        reason: this.overrideForm.reason || undefined,
      })
      .subscribe({
        next: () => this.overrideStatus.set('با موفقیت ثبت شد'),
        error: () => this.overrideStatus.set('خطا در ثبت مقدار دستی'),
      });
  }
}
