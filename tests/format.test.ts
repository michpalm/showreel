import { describe, expect, it } from 'vitest';
import { formatElapsed, formatSize } from '../src/format';

describe('formatElapsed', () => {
    it('shows m:ss, then h:mm:ss', () => {
        expect(formatElapsed(0)).toBe('0:00');
        expect(formatElapsed(7)).toBe('0:07');
        expect(formatElapsed(754.6)).toBe('12:34');
        expect(formatElapsed(3723)).toBe('1:02:03');
    });
});

describe('formatSize', () => {
    it('uses KB, MB, then GB with one decimal', () => {
        expect(formatSize(0)).toBe('0 KB');
        expect(formatSize(850_000)).toBe('850 KB');
        expect(formatSize(18_200_000)).toBe('18 MB');
        expect(formatSize(1_234_000_000)).toBe('1.2 GB');
    });
});
