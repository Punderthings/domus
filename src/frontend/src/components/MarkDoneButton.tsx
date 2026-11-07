import { Button, Group, Modal, Select, Stack, TextInput, Textarea } from '@mantine/core';
import { useForm } from '@mantine/form';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useCompleteTask, type CompleteInput } from '../api/mutations';
import type { MaintenanceTask } from '../api/types';
import { formatDate, isoDay } from '../format';
import { COST_PATTERN } from './deviceFormValues';
import { ErrorNotice } from './States';

const OUTCOMES = [
  { value: 'done', label: 'Done' },
  { value: 'partial', label: 'Partly done' },
  { value: 'skipped', label: 'Skipped' },
  { value: 'failed', label: 'Failed' },
];

interface Values {
  performed_on: string;
  outcome: NonNullable<CompleteInput['outcome']>;
  cost: string;
  notes: string;
}

/** "Mark done": log work on a task, with an optional cost, and let the server reschedule it. */
export function MarkDoneButton({ task, currency }: { task: MaintenanceTask; currency: string }) {
  const [opened, { open, close }] = useDisclosure(false);
  const complete = useCompleteTask();
  const form = useForm<Values>({
    initialValues: { performed_on: isoDay(), outcome: 'done', cost: '', notes: '' },
    validate: {
      performed_on: (v) =>
        !/^\d{4}-\d{2}-\d{2}$/.test(v)
          ? 'Pick a date'
          : v > isoDay()
            ? 'The date cannot be in the future'
            : null,
      cost: (v) => (v.trim() && !COST_PATTERN.test(v.trim()) ? 'Use a number such as 49.99' : null),
    },
  });

  const onClose = () => {
    close();
    form.reset();
    complete.reset();
  };

  const submit = form.onSubmit((values) => {
    const cost = values.cost.trim();
    complete.mutate(
      {
        taskId: task.id,
        body: {
          performed_on: values.performed_on,
          outcome: values.outcome,
          cost: cost || null,
          currency: cost ? currency : null,
          notes: values.notes.trim() || null,
        },
      },
      {
        onSuccess: (result) => {
          notifications.show({
            message: result.task.next_due
              ? `Logged. Next due ${formatDate(result.task.next_due)}.`
              : 'Logged.',
          });
          onClose();
        },
      },
    );
  });

  return (
    <>
      <Button size="xs" variant="light" onClick={open} aria-label={`Mark done: ${task.title}`}>
        Mark done
      </Button>
      <Modal opened={opened} onClose={onClose} title={task.title}>
        <form onSubmit={submit} noValidate>
          <Stack>
            <TextInput
              type="date"
              label="Done on"
              max={isoDay()}
              required
              {...form.getInputProps('performed_on')}
            />
            <Select
              label="Outcome"
              data={OUTCOMES}
              allowDeselect={false}
              {...form.getInputProps('outcome')}
            />
            <TextInput
              label={`Cost (${currency})`}
              inputMode="decimal"
              placeholder="Optional"
              {...form.getInputProps('cost')}
            />
            <Textarea label="Notes" autosize minRows={2} {...form.getInputProps('notes')} />
            {complete.isError && <ErrorNotice error={complete.error} />}
            <Group justify="flex-end">
              <Button variant="default" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" loading={complete.isPending}>
                Save
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </>
  );
}
