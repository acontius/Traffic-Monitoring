import { Injectable, OnDestroy } from '@angular/core';
import { Subject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { LiveEvent } from '../models/models';

/** Wraps the /ws/live push channel with auto-reconnect (SRS 3.6/3.8: the
 * dashboard and alert feed update live instead of polling). */
@Injectable({ providedIn: 'root' })
export class LiveSocketService implements OnDestroy {
  readonly events$ = new Subject<LiveEvent>();

  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  connect(): void {
    if (this.socket || this.stopped) {
      return;
    }
    this.socket = new WebSocket(environment.wsLiveUrl);

    this.socket.onmessage = (event) => {
      try {
        this.events$.next(JSON.parse(event.data) as LiveEvent);
      } catch {
        // ignore malformed frames
      }
    };

    this.socket.onclose = () => {
      this.socket = null;
      if (!this.stopped) {
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    };

    this.socket.onerror = () => this.socket?.close();
  }

  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.socket?.close();
    this.socket = null;
  }

  ngOnDestroy(): void {
    this.disconnect();
  }
}
