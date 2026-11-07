// Draws an image with device pins on it, using Konva (MIT). Positions come in and
// go out as 0-1 fractions of the image; only this component deals in pixels.

import { useElementSize } from '@mantine/hooks';
import type Konva from 'konva';
import { useEffect, useState } from 'react';
import { Circle, Group, Image as KonvaImage, Layer, Stage, Text } from 'react-konva';
import { clamp01, fitToWidth, toNormalized, toPixels, type Size } from './pins';

export interface Pin {
  id: string;
  x: number;
  y: number;
  label: string;
}

interface Props {
  imageUrl: string;
  alt: string;
  pins: Pin[];
  /** Pins can be dragged. */
  editable: boolean;
  /** The next click on the image places a pin there. */
  placing: boolean;
  onPlace: (x: number, y: number) => void;
  onPinMove: (id: string, x: number, y: number) => void;
  onPinClick: (id: string) => void;
}

const PIN_RADIUS = 9;

/** Load an image element; `null` until it has loaded. */
function useImage(url: string): [HTMLImageElement | null, boolean] {
  const [state, setState] = useState<{
    url: string;
    image: HTMLImageElement | null;
    failed: boolean;
  }>({ url, image: null, failed: false });
  useEffect(() => {
    const image = new window.Image();
    image.onload = () => setState({ url, image, failed: false });
    image.onerror = () => setState({ url, image: null, failed: true });
    image.src = url;
    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [url]);
  // Keep showing the old image while a replacement loads.
  return [state.image, state.url === url && state.failed];
}

function setCursor(event: Konva.KonvaEventObject<MouseEvent>, cursor: string) {
  const container = event.target.getStage()?.container();
  if (container) container.style.cursor = cursor;
}

export function PinCanvas(props: Props) {
  const { imageUrl, alt, pins, editable, placing, onPlace, onPinMove, onPinClick } = props;
  const { ref, width } = useElementSize();
  const [image, failed] = useImage(imageUrl);
  const natural: Size = image
    ? { width: image.naturalWidth, height: image.naturalHeight }
    : { width: 0, height: 0 };
  const drawn = fitToWidth(natural, width);

  const handleStageClick = (event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
    if (!placing) return;
    const point = event.target.getStage()?.getPointerPosition();
    if (!point) return;
    const at = toNormalized(point, drawn);
    onPlace(at.x, at.y);
  };

  return (
    <div ref={ref} role="img" aria-label={alt} style={{ width: '100%' }}>
      {failed && <span>The image could not be loaded.</span>}
      {image && drawn.width > 0 && (
        <Stage
          width={drawn.width}
          height={drawn.height}
          onClick={handleStageClick}
          onTap={handleStageClick}
          style={{ cursor: placing ? 'crosshair' : 'default' }}
        >
          <Layer>
            <KonvaImage image={image} width={drawn.width} height={drawn.height} />
            {pins.map((pin) => {
              const at = toPixels(pin, drawn);
              return (
                <Group
                  key={pin.id}
                  x={at.x}
                  y={at.y}
                  draggable={editable}
                  dragBoundFunc={(pos) => ({
                    x: clamp01(pos.x / drawn.width) * drawn.width,
                    y: clamp01(pos.y / drawn.height) * drawn.height,
                  })}
                  onDragEnd={(event) => {
                    const moved = toNormalized(event.target.position(), drawn);
                    onPinMove(pin.id, moved.x, moved.y);
                  }}
                  onClick={(event) => {
                    event.cancelBubble = true;
                    onPinClick(pin.id);
                  }}
                  onTap={(event) => {
                    event.cancelBubble = true;
                    onPinClick(pin.id);
                  }}
                  onMouseEnter={(event) => setCursor(event, editable ? 'move' : 'pointer')}
                  onMouseLeave={(event) => setCursor(event, placing ? 'crosshair' : 'default')}
                >
                  <Circle radius={PIN_RADIUS} fill="#1c7ed6" stroke="#ffffff" strokeWidth={2} />
                  <Text
                    text={pin.label}
                    x={PIN_RADIUS + 4}
                    y={-7}
                    fontSize={13}
                    fill="#ffffff"
                    stroke="#000000"
                    strokeWidth={3}
                    fillAfterStrokeEnabled
                  />
                </Group>
              );
            })}
          </Layer>
        </Stage>
      )}
    </div>
  );
}
