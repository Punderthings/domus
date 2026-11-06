// Mantine components wired to the router, so `to` and `params` are type-checked.
import { Anchor, Card, type AnchorProps, type CardProps } from '@mantine/core';
import { createLink } from '@tanstack/react-router';
import { forwardRef, type ComponentPropsWithoutRef } from 'react';

const RouterAnchor = forwardRef<HTMLAnchorElement, AnchorProps & ComponentPropsWithoutRef<'a'>>(
  (props, ref) => <Anchor ref={ref} {...props} />,
);
RouterAnchor.displayName = 'RouterAnchor';

const RouterCard = forwardRef<HTMLAnchorElement, CardProps & ComponentPropsWithoutRef<'a'>>(
  (props, ref) => <Card ref={ref} component="a" {...props} />,
);
RouterCard.displayName = 'RouterCard';

export const AnchorLink = createLink(RouterAnchor);
export const CardLink = createLink(RouterCard);
