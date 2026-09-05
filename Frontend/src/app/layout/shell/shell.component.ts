import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Subscription } from 'rxjs';
import { AlertService } from '../../core/services/alert.service';
import { AuthService } from '../../core/services/auth.service';
import { LiveSocketService } from '../../core/services/live-socket.service';
import { Alert } from '../../core/models/models';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent implements OnInit, OnDestroy {
  readonly unacknowledgedCount = signal(0);
  readonly toast = signal<Alert | null>(null);

  private subscription?: Subscription;
  private toastTimer?: ReturnType<typeof setTimeout>;

  constructor(
    private readonly alertService: AlertService,
    private readonly liveSocket: LiveSocketService,
    readonly auth: AuthService,
  ) {}

  ngOnInit(): void {
    this.refreshCount();
    this.liveSocket.connect();
    this.subscription = this.liveSocket.events$.subscribe((event) => {
      if (event.event === 'alert') {
        const alert = event.data as Alert;
        this.unacknowledgedCount.update((n) => n + 1);
        this.showToast(alert);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  logout(): void {
    this.auth.logout();
  }

  private refreshCount(): void {
    this.alertService
      .list(true)
      .subscribe((alerts) => this.unacknowledgedCount.set(alerts.length));
  }

  private showToast(alert: Alert): void {
    this.toast.set(alert);
    if (this.toastTimer) {
      clearTimeout(this.toastTimer);
    }
    this.toastTimer = setTimeout(() => this.toast.set(null), 6000);
  }
}
