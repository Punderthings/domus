import { Alert, Button, PasswordInput, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { Navigate, useNavigate } from '@tanstack/react-router';
import { ApiError } from '../api/client';
import { useCurrentUser, useLogin, useSetupStatus } from '../api/queries';
import { PageLoader } from '../components/States';
import { AuthCard } from './AuthCard';

export function LoginPage() {
  const navigate = useNavigate();
  const user = useCurrentUser();
  const setup = useSetupStatus();
  const login = useLogin();
  const form = useForm({
    initialValues: { email: '', password: '' },
    validate: {
      email: (value) => (/^\S+@\S+$/.test(value) ? null : 'Enter an email address'),
      password: (value) => (value ? null : 'Enter your password'),
    },
  });

  if (user.isPending || setup.isPending) return <PageLoader />;
  if (setup.data?.needs_setup) return <Navigate to="/setup" />;
  if (user.data) return <Navigate to="/" />;

  const failed =
    login.error instanceof ApiError && (login.error.status === 400 || login.error.status === 401)
      ? 'That email and password did not match.'
      : login.error
        ? login.error instanceof ApiError && login.error.status === 429
          ? 'Too many attempts. Wait a minute and try again.'
          : 'Could not sign in. Check that the Domus server is running.'
        : null;

  return (
    <AuthCard title="Sign in to Domus">
      <form
        onSubmit={form.onSubmit((values) =>
          login.mutate(values, { onSuccess: () => void navigate({ to: '/' }) }),
        )}
      >
        <Stack>
          {failed && (
            <Alert color="red" role="alert">
              {failed}
            </Alert>
          )}
          <TextInput
            label="Email"
            type="email"
            autoComplete="username"
            required
            {...form.getInputProps('email')}
          />
          <PasswordInput
            label="Password"
            autoComplete="current-password"
            required
            {...form.getInputProps('password')}
          />
          <Button type="submit" loading={login.isPending}>
            Sign in
          </Button>
        </Stack>
      </form>
    </AuthCard>
  );
}
