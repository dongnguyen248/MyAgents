export const secondsAgo = (s: number) => new Date(Date.now() - s * 1000).toISOString();
export const minutesAgo = (m: number) => secondsAgo(m * 60);
