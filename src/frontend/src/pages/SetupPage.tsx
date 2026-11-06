import { Alert, Button, PasswordInput, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { Navigate, useNavigate } from '@tanstack/react-router';
import { useSetup, useSetupStatus } from '../api/queries';
import { PageLoader } from '../components/States';
import { AuthCard } from './AuthCard';

export const MIN_PASSWORD_LENGTH = 12;

/** First-run wizard: creates the first Admin and the property. No default credentials exist. */
export function SetupPage() {
  const navigate = useNavigate();
  const status = useSetupStatus();
  const setup = useSetup();
  const form = useForm({
    initialValues: { property_name: '', display_name: '', email: '', password: '', confirm: '' },
    validate: {
      property_name: (value) => (value.trim() ? null : 'Name your property, such as "Our house"'),
      display_name: (value) => (value.trim() ? null : 'Enter your name'),
      email: (value) => (/^\S+@\S+$/.test(value) ? null : 'Enter an email address'),
      password: (value) =>
        value.length >= MIN_PASSWORD_LENGTH
          ? null
          : `Use at least ${MIN_PASSWORD_LENGTH} characters`,
      confirm: (value, values) => (value === values.password ? null : 'Passwords do not match'),
    },
  });

  if (status.isPending) return <PageLoader />;
  if (status.data && !status.data.needs_setup) return <Navigate to="/login" />;

  return (
    <AuthCard title="Welcome to Domus" subtitle="Create the first Admin account and your property.">
      <form
        onSubmit={form.onSubmit((values) =>
          setup.mutate(
            {
              email: values.email,
              password: values.password,
              property_name: values.property_name.trim(),
              display_name: values.display_name.trim(),
            },
            { onSuccess: () => void navigate({ to: '/' }) },
          ),
        )}
      >
        <Stack>
          {setup.error && (
            <Alert color="red" role="alert">
              Setup failed: {setup.error.message}
            </Alert>
          )}
          <TextInput label="Property name" required {...form.getInputProps('property_name')} />
          <TextInput
            label="Your name"
            autoComplete="name"
            required
            {...form.getInputProps('display_name')}
          />
          <TextInput
            label="Email"
            type="email"
            autoComplete="username"
            required
            {...form.getInputProps('email')}
          />
          <PasswordInput
            label="Password"
            autoComplete="new-password"
            description={`At least ${MIN_PASSWORD_LENGTH} characters`}
            required
            {...form.getInputProps('password')}
          />
          <PasswordInput
            label="Confirm password"
            autoComplete="new-password"
            required
            {...form.getInputProps('confirm')}
          />
          <Button type="submit" loading={setup.isPending}>
            Create account
          </Button>
        </Stack>
      </form>
    </AuthCard>
  );
}
