
import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';

@Component({
    selector: 'app-login',
    imports: [FormsModule],
    templateUrl: './login.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrl: './login.component.scss'
})
export class LoginComponent {
  username = '';
  password = '';
  readonly loading = signal(false);
  readonly errorMessage = signal<string | null>(null);

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
  ) {}

  async submit(): Promise<void> {
    this.errorMessage.set(null);
    this.loading.set(true);
    try {
      await this.auth.login(this.username, this.password);
      this.router.navigateByUrl('/dashboard');
    } catch {
      this.errorMessage.set('نام کاربری یا رمز عبور نادرست است');
    } finally {
      this.loading.set(false);
    }
  }
}
