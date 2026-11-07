import { Alert, Breadcrumbs, Stack, Text, Title } from '@mantine/core';
import { useNavigate, useParams } from '@tanstack/react-router';
import { useAsset } from '../api/queries';
import { allows, hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { DeviceForm } from '../components/DeviceForm';
import { AnchorLink } from '../components/links';
import { ErrorNotice, PageLoader } from '../components/States';
import { terms } from '../terms';

function NoAccess() {
  return (
    <Alert color="yellow" title="Not allowed">
      Only Maintainers and Admins can add or change {terms.devices.toLowerCase()}.
    </Alert>
  );
}

export function DeviceNewPage() {
  const membership = useActiveMembership();
  const navigate = useNavigate();
  const role = membership ? toRole(membership.role) : undefined;
  if (!membership) return null;

  return (
    <Stack>
      <Breadcrumbs>
        <AnchorLink to="/devices">{terms.devices}</AnchorLink>
        <Text>New</Text>
      </Breadcrumbs>
      <Title order={2}>Add a {terms.device.toLowerCase()}</Title>
      {hasRole(role, 'maintainer') ? (
        <DeviceForm
          propertyId={membership.property_id}
          isAdmin={hasRole(role, 'admin')}
          onSaved={(deviceId) => void navigate({ to: '/devices/$deviceId', params: { deviceId } })}
          onCancel={() => void navigate({ to: '/devices' })}
        />
      ) : (
        <NoAccess />
      )}
    </Stack>
  );
}

export function DeviceEditPage() {
  const { deviceId } = useParams({ from: '/app/devices/$deviceId/edit' });
  const membership = useActiveMembership();
  const navigate = useNavigate();
  const device = useAsset(deviceId);
  const role = membership ? toRole(membership.role) : undefined;

  if (device.isPending) return <PageLoader />;
  if (device.isError) return <ErrorNotice error={device.error} />;
  if (!membership) return null;
  const toDevice = () => void navigate({ to: '/devices/$deviceId', params: { deviceId } });

  return (
    <Stack>
      <Breadcrumbs>
        <AnchorLink to="/devices">{terms.devices}</AnchorLink>
        <AnchorLink to="/devices/$deviceId" params={{ deviceId }}>
          {device.data.name}
        </AnchorLink>
        <Text>Edit</Text>
      </Breadcrumbs>
      <Title order={2}>Edit {device.data.name}</Title>
      {hasRole(role, 'maintainer') && allows(device.data.access, 'manage') ? (
        <DeviceForm
          propertyId={membership.property_id}
          device={device.data}
          isAdmin={hasRole(role, 'admin')}
          onSaved={toDevice}
          onCancel={toDevice}
        />
      ) : (
        <NoAccess />
      )}
    </Stack>
  );
}
