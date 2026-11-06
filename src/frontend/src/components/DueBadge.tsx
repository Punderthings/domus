import { Badge } from '@mantine/core';
import { dueState, formatDate } from '../format';

const COLORS = { overdue: 'red', due: 'yellow', upcoming: 'gray', none: 'gray' } as const;

export function DueBadge({
  nextDue,
  leadDays,
}: {
  nextDue: string | null;
  leadDays: number | null;
}) {
  const state = dueState(nextDue, leadDays);
  const label =
    state === 'none'
      ? 'Not scheduled'
      : state === 'overdue'
        ? `Overdue since ${formatDate(nextDue)}`
        : `Due ${formatDate(nextDue)}`;
  return (
    <Badge color={COLORS[state]} variant="light" style={{ flexShrink: 0 }}>
      {label}
    </Badge>
  );
}
