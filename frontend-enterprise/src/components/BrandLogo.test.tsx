// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import BrandLogo from './BrandLogo';

afterEach(cleanup);

describe('BrandLogo', () => {
  it('renders the QuantXY mark on the left of its wordmark', () => {
    const { container } = render(<BrandLogo />);

    const mark = container.querySelector('img');
    const wordmark = screen.getByText('QuantXY').parentElement;

    expect(mark?.getAttribute('alt')).toBe('');
    expect(screen.getByText('量子星河')).toBeTruthy();
    expect(mark?.nextElementSibling).toBe(wordmark);
    expect(container.querySelector('strong')?.textContent).toBe('QuantXY');
  });

  it('keeps only the QuantXY mark when collapsed', () => {
    render(<BrandLogo markOnly />);

    expect(screen.getByRole('img', { name: 'QuantXY' })).toBeTruthy();
    expect(screen.queryByText('QuantXY')).toBeNull();
    expect(screen.queryByText('量子星河')).toBeNull();
  });
});
