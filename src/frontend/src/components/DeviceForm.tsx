// The add/edit form for a device (an "asset" in the API). Fields follow the AssetIn and
// AssetUpdate schemas; manufacturer, model, and manual link live on a shared product.

import {
  Button,
  Card,
  Checkbox,
  Group,
  Select,
  SimpleGrid,
  Stack,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useState } from 'react';
import {
  useCreateAsset,
  useCreateLocation,
  useCreateProduct,
  useLocations,
  useUpdateAsset,
} from '../api/mutations';
import { useAreas } from '../api/queries';
import type { AssetDetail } from '../api/types';
import { allows } from '../auth/permissions';
import { terms } from '../terms';
import {
  CATEGORIES,
  LOCATION_KINDS,
  NEW_LOCATION,
  STATUSES,
  changedFields,
  initialValues,
  options,
  orNull,
  productChanged,
  validate,
  type DeviceValues,
} from './deviceFormValues';
import { ErrorNotice } from './States';

interface Props {
  propertyId: string;
  /** The device being edited; leave out to add a new one. */
  device?: AssetDetail;
  isAdmin: boolean;
  onSaved: (deviceId: string) => void;
  onCancel: () => void;
}

export function DeviceForm({ propertyId, device, isAdmin, onSaved, onCancel }: Props) {
  const [initial] = useState(() => initialValues(device));
  const form = useForm<DeviceValues>({ initialValues: initial, validate });
  const areas = useAreas(propertyId);
  const locations = useLocations(form.values.area_id || null);
  const createLocation = useCreateLocation();
  const createProduct = useCreateProduct(propertyId);
  const createAsset = useCreateAsset();
  const updateAsset = useUpdateAsset(device?.id ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Devices can only go where the user may manage things.
  const areaOptions = (areas.data?.items ?? [])
    .filter((area) => allows(area.access, 'manage'))
    .map((area) => ({ value: area.id, label: area.name }))
    .sort((a, b) => a.label.localeCompare(b.label));
  const locationOptions = [
    ...(locations.data?.items ?? [])
      .map((loc) => ({ value: loc.id, label: loc.name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    { value: NEW_LOCATION, label: 'New location…' },
  ];

  const submit = form.onSubmit(async (values) => {
    setSaving(true);
    setError(null);
    try {
      let locationId: string | null = values.location_id || null;
      if (!values.area_id) {
        locationId = null;
      } else if (locationId === NEW_LOCATION) {
        const created = await createLocation.mutateAsync({
          area_id: values.area_id,
          name: values.new_location_name.trim(),
          kind: values.new_location_kind,
        });
        locationId = created.id;
      }

      let productId: string | null | undefined = undefined;
      if (productChanged(values, initial)) {
        const hasProduct = [values.manufacturer, values.model, values.manual_url].some((v) =>
          v.trim(),
        );
        productId = hasProduct
          ? (
              await createProduct.mutateAsync({
                manufacturer: orNull(values.manufacturer),
                model: orNull(values.model),
                manual_url: orNull(values.manual_url),
                category: values.category,
              })
            ).id
          : null;
      }

      if (device) {
        const body = changedFields(values, initial);
        if (productId !== undefined) body.product_id = productId;
        if (locationId !== (initial.location_id || null)) body.location_id = locationId;
        if (isAdmin && values.is_critical !== initial.is_critical) {
          body.is_critical = values.is_critical;
        }
        const saved = Object.keys(body).length ? await updateAsset.mutateAsync(body) : device;
        onSaved(saved.id);
      } else {
        const serial = values.serial.trim();
        const created = await createAsset.mutateAsync({
          property_id: propertyId,
          name: values.name.trim(),
          category: values.category,
          status: values.status,
          product_id: productId ?? null,
          location_id: locationId,
          install_date: orNull(values.install_date),
          purchase_date: orNull(values.purchase_date),
          purchase_price: orNull(values.purchase_price),
          vendor: orNull(values.vendor),
          warranty_expires: orNull(values.warranty_expires),
          is_critical: isAdmin && values.is_critical,
          notes: orNull(values.notes),
          identifiers: serial ? [{ kind: 'serial', value: serial, source: 'manual' }] : [],
        });
        onSaved(created.id);
      }
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack>
        <Card withBorder>
          <Stack>
            <TextInput label="Name" required autoFocus {...form.getInputProps('name')} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label="Category"
                data={options(CATEGORIES)}
                allowDeselect={false}
                {...form.getInputProps('category')}
              />
              <Select
                label="Status"
                data={options(STATUSES)}
                allowDeselect={false}
                {...form.getInputProps('status')}
              />
            </SimpleGrid>
            {isAdmin && (
              <Checkbox
                label="Critical (only Admins can change it)"
                {...form.getInputProps('is_critical', { type: 'checkbox' })}
              />
            )}
          </Stack>
        </Card>

        <Card withBorder>
          <Title order={3} mb="sm">
            Where it is
          </Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={terms.area}
              placeholder={`No ${terms.area.toLowerCase()}`}
              data={areaOptions}
              searchable
              clearable
              {...form.getInputProps('area_id')}
              value={form.values.area_id || null}
              onChange={(value) => {
                form.setFieldValue('area_id', value ?? '');
                form.setFieldValue('location_id', '');
              }}
            />
            <Select
              label="Location"
              placeholder="Pick or add one"
              data={locationOptions}
              disabled={!form.values.area_id}
              clearable
              {...form.getInputProps('location_id')}
              value={form.values.location_id || null}
              onChange={(value) => form.setFieldValue('location_id', value ?? '')}
            />
          </SimpleGrid>
          {form.values.location_id === NEW_LOCATION && (
            <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
              <TextInput
                label="New location name"
                placeholder="Under the sink"
                required
                {...form.getInputProps('new_location_name')}
              />
              <Select
                label="Kind"
                data={options(LOCATION_KINDS)}
                allowDeselect={false}
                {...form.getInputProps('new_location_kind')}
              />
            </SimpleGrid>
          )}
        </Card>

        <Card withBorder>
          <Title order={3} mb="sm">
            Make and model
          </Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Manufacturer" {...form.getInputProps('manufacturer')} />
            <TextInput label="Model" {...form.getInputProps('model')} />
            <TextInput
              label="Manual link"
              placeholder="https://"
              type="url"
              {...form.getInputProps('manual_url')}
            />
            {!device && <TextInput label="Serial number" {...form.getInputProps('serial')} />}
          </SimpleGrid>
        </Card>

        <Card withBorder>
          <Title order={3} mb="sm">
            Purchase and warranty
          </Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput type="date" label="Installed" {...form.getInputProps('install_date')} />
            <TextInput type="date" label="Purchased" {...form.getInputProps('purchase_date')} />
            <TextInput
              label="Purchase price"
              inputMode="decimal"
              {...form.getInputProps('purchase_price')}
            />
            <TextInput label="Vendor" {...form.getInputProps('vendor')} />
            <TextInput
              type="date"
              label="Warranty until"
              {...form.getInputProps('warranty_expires')}
            />
          </SimpleGrid>
        </Card>

        <Textarea label="Notes" autosize minRows={3} {...form.getInputProps('notes')} />

        {error !== null && <ErrorNotice error={error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={saving}>
            {device ? 'Save changes' : `Add ${terms.device.toLowerCase()}`}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
