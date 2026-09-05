import { HttpClient } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { TokenResponse } from '../models/models';

const ACCESS_TOKEN_KEY = 'tcms_access_token';
const REFRESH_TOKEN_KEY = 'tcms_refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly isAuthenticated = signal<boolean>(!!this.accessToken);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  get accessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }

  get refreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  private storeTokens(tokens: TokenResponse): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    this.isAuthenticated.set(true);
  }

  async login(username: string, password: string): Promise<void> {
    const tokens = await firstValueFrom(
      this.http.post<TokenResponse>(`${environment.apiBaseUrl}/auth/login`, {
        username,
        password,
      }),
    );
    this.storeTokens(tokens);
  }

  async refresh(): Promise<string> {
    const refreshToken = this.refreshToken;
    if (!refreshToken) {
      throw new Error('no refresh token available');
    }
    const tokens = await firstValueFrom(
      this.http.post<TokenResponse>(`${environment.apiBaseUrl}/auth/refresh`, {
        refresh_token: refreshToken,
      }),
    );
    this.storeTokens(tokens);
    return tokens.access_token;
  }

  async logout(): Promise<void> {
    const refreshToken = this.refreshToken;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    this.isAuthenticated.set(false);
    if (refreshToken) {
      try {
        await firstValueFrom(
          this.http.post(`${environment.apiBaseUrl}/auth/logout`, {
            refresh_token: refreshToken,
          }),
        );
      } catch {
        // best-effort server-side revocation; local session is already cleared
      }
    }
    this.router.navigateByUrl('/login');
  }
}
