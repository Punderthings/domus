// PinCanvas with react-konva swapped for plain elements: jsdom has no canvas.
import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PinCanvas } from './PinCanvas';

interface Handlers {
  onClick?: (e: unknown) => void;
  onDragEnd?: (e: unknown) => void;
  dragBoundFunc?: (pos: { x: number; y: number }) => { x: number; y: number };
}
const groups: Handlers[] = [];
let pointer = { x: 0, y: 0 };

vi.mock('react-konva', () => ({
  Stage: ({
    children,
    onClick,
    width,
    height,
  }: Handlers & { children: ReactNode; width: number; height: number }) => (
    <div
      data-testid="stage"
      data-size={`${width}x${height}`}
      onClick={() =>
        onClick?.({ target: { getStage: () => ({ getPointerPosition: () => pointer }) } })
      }
    >
      {children}
    </div>
  ),
  Layer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Image: () => <div data-testid="image" />,
  Circle: () => null,
  Text: ({ text }: { text: string }) => <span>{text}</span>,
  Group: (props: Handlers & { children: ReactNode }) => {
    groups.push(props);
    return <div>{props.children}</div>;
  },
}));

vi.mock('@mantine/hooks', async (original) => ({
  ...(await original<typeof import('@mantine/hooks')>()),
  useElementSize: () => ({ ref: () => {}, width: 400, height: 0 }),
}));

class FakeImage {
  naturalWidth = 800;
  naturalHeight = 400;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_value: string) {
    queueMicrotask(() => this.onload?.());
  }
}

function setup(over: Partial<Parameters<typeof PinCanvas>[0]> = {}) {
  const props = {
    imageUrl: '/plan.png',
    alt: 'Plan',
    pins: [{ id: 'p1', x: 0.5, y: 0.25, label: 'Fridge' }],
    editable: true,
    placing: false,
    onPlace: vi.fn(),
    onPinMove: vi.fn(),
    onPinClick: vi.fn(),
    ...over,
  };
  render(
    <MantineProvider>
      <PinCanvas {...props} />
    </MantineProvider>,
  );
  return props;
}

beforeEach(() => {
  groups.length = 0;
  vi.stubGlobal('Image', FakeImage);
});

describe('PinCanvas', () => {
  it('fits the image to the available width', async () => {
    setup();
    expect(await screen.findByTestId('stage')).toHaveAttribute('data-size', '400x200');
    expect(screen.getByText('Fridge')).toBeInTheDocument();
  });

  it('reports a drag as a 0-1 position', async () => {
    const props = setup();
    await screen.findByTestId('stage');
    groups.at(-1)?.onDragEnd?.({ target: { position: () => ({ x: 100, y: 150 }) } });
    expect(props.onPinMove).toHaveBeenCalledWith('p1', 0.25, 0.75);
  });

  it('keeps a dragged pin on the image', async () => {
    setup();
    await screen.findByTestId('stage');
    expect(groups.at(-1)?.dragBoundFunc?.({ x: -20, y: 900 })).toEqual({ x: 0, y: 200 });
  });

  it('places a pin where the image is clicked, only while placing', async () => {
    const idle = setup();
    fireEvent.click(await screen.findByTestId('stage'));
    expect(idle.onPlace).not.toHaveBeenCalled();
  });

  it('places at the clicked point', async () => {
    const props = setup({ placing: true });
    pointer = { x: 300, y: 50 };
    fireEvent.click(await screen.findByTestId('stage'));
    expect(props.onPlace).toHaveBeenCalledWith(0.75, 0.25);
  });
});
