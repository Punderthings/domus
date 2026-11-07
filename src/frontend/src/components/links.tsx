// Mantine components wired to the router, so `to` and `params` are type-checked.
import {
  Anchor,
  Button,
  Card,
  type AnchorProps,
  type ButtonProps,
  type CardProps,
} from '@mantine/core';
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

const RouterButton = forwardRef<HTMLAnchorElement, ButtonProps & ComponentPropsWithoutRef<'a'>>(
  (props, ref) => <Button ref={ref} component="a" {...props} />,
);
RouterButton.displayName = 'RouterButton';

export const AnchorLink = createLink(RouterAnchor);
export const CardLink = createLink(RouterCard);
export const ButtonLink = createLink(RouterButton);
