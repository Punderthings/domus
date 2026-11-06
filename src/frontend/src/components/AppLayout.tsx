import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  Menu,
  NavLink,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Link, Navigate, Outlet, useRouterState } from '@tanstack/react-router';
import {
  useCurrentUser,
  useLogout,
  useProperties,
  useProperty,
  useSetupStatus,
} from '../api/queries';
import type { Property } from '../api/types';
import { ROLE_LABELS, toRole } from '../auth/permissions';
import { setActivePropertyId, useActiveMembership } from '../auth/useActiveProperty';
import { terms } from '../terms';
import { ErrorNotice, PageLoader } from './States';

const NAV = [
  { to: '/', label: 'Overview', exact: true },
  { to: '/devices', label: terms.devices, exact: false },
] as const;

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('light');
  const next = scheme === 'dark' ? 'light' : 'dark';
  return (
    <Tooltip label={`Switch to ${next} mode`}>
      <ActionIcon
        variant="default"
        size="lg"
        aria-label={`Switch to ${next} mode`}
        onClick={() => setColorScheme(next)}
      >
        <span aria-hidden="true">{scheme === 'dark' ? '☀' : '☾'}</span>
      </ActionIcon>
    </Tooltip>
  );
}

/** Menu items to switch property, shown only to members of more than one. */
function PropertySwitcher({
  properties,
  activeId,
}: {
  properties: Property[];
  activeId: string | undefined;
}) {
  if (properties.length < 2) return null;
  return (
    <>
      <Menu.Divider />
      <Menu.Label>Property</Menu.Label>
      {properties.map((p) => (
        <Menu.Item
          key={p.id}
          aria-current={p.id === activeId ? 'true' : undefined}
          fw={p.id === activeId ? 600 : undefined}
          onClick={() => setActivePropertyId(p.id)}
        >
          {p.name}
        </Menu.Item>
      ))}
      <Menu.Divider />
    </>
  );
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const user = useCurrentUser();
  const setup = useSetupStatus();
  const membership = useActiveMembership();
  const property = useProperty(membership?.property_id);
  // Loaded up front, so the account menu has the names when it opens.
  const properties = useProperties((user.data?.memberships.length ?? 0) > 1);
  const logout = useLogout();
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  if (user.isPending || setup.isPending) return <PageLoader />;
  if (setup.data?.needs_setup) return <Navigate to="/setup" />;
  if (user.isError) return <ErrorNotice error={user.error} />;
  if (!user.data) return <Navigate to="/login" />;

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Title order={3}>Domus</Title>
            {property.data && (
              <Text c="dimmed" visibleFrom="xs" truncate>
                {property.data.name}
              </Text>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            <ColorSchemeToggle />
            <Menu position="bottom-end">
              <Menu.Target>
                <ActionIcon variant="default" size="lg" aria-label="Account">
                  <span aria-hidden="true">{user.data.display_name.slice(0, 1).toUpperCase()}</span>
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>
                  {user.data.display_name}
                  {membership && (
                    <Badge ml="xs" size="xs" variant="light">
                      {ROLE_LABELS[toRole(membership.role)]}
                    </Badge>
                  )}
                </Menu.Label>
                <PropertySwitcher
                  properties={properties.data?.items ?? []}
                  activeId={membership?.property_id}
                />
                <Menu.Item onClick={() => logout.mutate()}>Sign out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" aria-label="Main">
        {NAV.map((item) => {
          const active = item.exact ? pathname === item.to : pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              component={Link}
              to={item.to}
              label={item.label}
              active={active}
              onClick={close}
            />
          );
        })}
      </AppShell.Navbar>

      <AppShell.Main>
        {membership ? (
          <Outlet />
        ) : (
          <Text>Your account is not a member of any property yet. Ask an Admin to invite you.</Text>
        )}
      </AppShell.Main>
    </AppShell>
  );
}
