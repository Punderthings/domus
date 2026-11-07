import { Button, FileButton, Group, TextInput } from '@mantine/core';
import { useState } from 'react';
import { useCreateCanvas } from '../api/queries';
import type { CanvasKind } from '../api/types';
import { IMAGE_ACCEPT } from './CanvasEditor';
import { ErrorNotice } from './States';

interface Props {
  propertyId: string;
  scope: { type: 'floor' | 'area'; id: string };
  kind: CanvasKind;
  label: string;
  /** Ask for a name first (wall photos); floor plans are named after the floor. */
  askName?: boolean;
}

/** Upload an image as a new floor plan or wall photo. */
export function NewCanvasButton({ propertyId, scope, kind, label, askName = false }: Props) {
  const create = useCreateCanvas();
  const [name, setName] = useState('');
  return (
    <>
      <Group gap="xs" align="end">
        {askName && (
          <TextInput
            label="Photo name"
            placeholder="Switches by the back door"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            w={260}
          />
        )}
        <FileButton
          accept={IMAGE_ACCEPT}
          onChange={(file) => {
            if (!file) return;
            create.mutate(
              { propertyId, scope, kind, name: name.trim() || undefined, file },
              { onSuccess: () => setName('') },
            );
          }}
        >
          {(props) => (
            <Button {...props} loading={create.isPending}>
              {label}
            </Button>
          )}
        </FileButton>
      </Group>
      {create.error && <ErrorNotice error={create.error} />}
    </>
  );
}
