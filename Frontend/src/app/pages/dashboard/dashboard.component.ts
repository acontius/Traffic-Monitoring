import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import * as L from 'leaflet';
import { Subscription } from 'rxjs';
import { DeviceService } from '../../core/services/device.service';
import { LiveSocketService } from '../../core/services/live-socket.service';
import { Device, TrafficPayload, TrafficRecord } from '../../core/models/models';

interface DeviceRow {
  device: Device;
  latest: TrafficPayload | null;
  online: boolean;
}

const TYPE_LABELS: Record<string, string> = {
  urban: 'شهری',
  highway: 'اتوبانی',
  industrial: 'صنعتی',
};

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements AfterViewInit, OnDestroy {
  @ViewChild('mapEl') mapElRef!: ElementRef<HTMLDivElement>;

  rows: DeviceRow[] = [];
  typeLabels = TYPE_LABELS;

  private map: L.Map | null = null;
  private markers = new Map<string, L.Marker>();
  private subscription?: Subscription;

  constructor(
    private readonly deviceService: DeviceService,
    private readonly liveSocket: LiveSocketService,
  ) {}

  ngAfterViewInit(): void {
    this.map = L.map(this.mapElRef.nativeElement, { minZoom: 8 }).setView(
      [35.724, 51.42],
      11,
    );
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(this.map);

    this.loadDevices();
    this.liveSocket.connect();
    this.subscription = this.liveSocket.events$.subscribe((event) => {
      if (event.event === 'device_update') {
        const data = event.data as { device_id: string; status: string; latest: TrafficPayload | null };
        this.applyUpdate(data.device_id, data.status === 'online', data.latest);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
    this.map?.remove();
  }

  private loadDevices(): void {
    this.deviceService.list().subscribe((devices) => {
      this.rows = devices.map((device) => ({ device, latest: null, online: device.status === 'online' }));
      for (const device of devices) {
        if (device.latitude != null && device.longitude != null) {
          this.addMarker(device);
        }
      }
      this.deviceService.latestAll().subscribe((records: TrafficRecord[]) => {
        for (const record of records) {
          this.applyUpdate(record.device_id, true, record.payload);
        }
      });
    });
  }

  private addMarker(device: Device): void {
    const marker = L.marker([device.latitude!, device.longitude!], {
      icon: this.buildIcon(false),
    });
    marker.bindPopup(this.buildPopupHtml(device, null));
    marker.addTo(this.map!);
    this.markers.set(device.device_id, marker);
  }

  private applyUpdate(deviceId: string, online: boolean, latest: TrafficPayload | null): void {
    const row = this.rows.find((r) => r.device.device_id === deviceId);
    if (row) {
      row.online = online;
      row.latest = latest ?? row.latest;
    }
    const marker = this.markers.get(deviceId);
    if (marker) {
      marker.setIcon(this.buildIcon(online));
      const device = row?.device;
      if (device) {
        marker.bindPopup(this.buildPopupHtml(device, latest ?? row?.latest ?? null));
      }
    }
  }

  private buildIcon(active: boolean): L.DivIcon {
    const stateClass = active ? 'camera-marker--active' : 'camera-marker--inactive';
    return L.divIcon({
      html: `<div class="camera-marker ${stateClass}"><div class="camera-marker__pulse"></div><div class="camera-marker__core">📷</div></div>`,
      className: '',
      iconSize: [46, 46],
      iconAnchor: [23, 23],
    });
  }

  private buildPopupHtml(device: Device, latest: TrafficPayload | null): string {
    const label = device.label || device.device_id;
    const typeLabel = TYPE_LABELS[device.location_type] || device.location_type;
    return `
      <div>
        <strong>${label}</strong><br/>
        ${device.device_id} • ${typeLabel}<br/>
        آخرین زمان: ${latest?.timestamp ?? '—'}
      </div>
    `;
  }

  totalCount(row: DeviceRow): number {
    if (!row.latest?.counts) return 0;
    return Object.values(row.latest.counts).reduce((sum, value) => sum + value, 0);
  }
}
