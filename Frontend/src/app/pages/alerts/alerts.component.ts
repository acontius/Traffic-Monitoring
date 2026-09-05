import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { AlertService } from '../../core/services/alert.service';
import { LiveSocketService } from '../../core/services/live-socket.service';
import { Alert } from '../../core/models/models';

@Component({
  selector: 'app-alerts',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './alerts.component.html',
  styleUrl: './alerts.component.scss',
})
export class AlertsComponent implements OnInit, OnDestroy {
  readonly alerts = signal<Alert[]>([]);
  readonly unacknowledgedOnly = signal(false);

  private subscription?: Subscription;

  constructor(
    private readonly alertService: AlertService,
    private readonly liveSocket: LiveSocketService,
  ) {}

  ngOnInit(): void {
    this.load();
    this.liveSocket.connect();
    this.subscription = this.liveSocket.events$.subscribe((event) => {
      if (event.event === 'alert') {
        this.alerts.update((current) => [event.data as Alert, ...current]);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  load(): void {
    this.alertService.list(this.unacknowledgedOnly()).subscribe((alerts) => this.alerts.set(alerts));
  }

  toggleFilter(): void {
    this.unacknowledgedOnly.update((v) => !v);
    this.load();
  }

  acknowledge(alert: Alert): void {
    this.alertService.acknowledge(alert.id).subscribe((updated) => {
      this.alerts.update((current) => current.map((a) => (a.id === updated.id ? updated : a)));
    });
  }
}
